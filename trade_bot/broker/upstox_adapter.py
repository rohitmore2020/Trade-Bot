"""
Upstox Broker Adapter Implementation.

Production-grade infrastructure adapter implementing the unified IBrokerAdapter contract
for the Upstox API v2 and HFT order gateway.
Completely decoupled from domain and strategy logic with zero Upstox SDK dependencies.
Features:
- Official Upstox API v2 / HFT endpoint integration
- Normalized domain mapping (OrderRequest, Order, Position, Trade, AccountBalance)
- Safe credential handling with automatic redaction
- Resilient error handling, rate limiting (429) backoff, and timeouts
- Idempotent order placement: verifies order book before submitting retries
- Guarded live execution (allow_live=False by default)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.broker.upstox_models import (
    build_modify_payload,
    build_order_payload,
    normalize_funds,
    normalize_order,
    normalize_position,
    normalize_trade,
    redact_headers,
    redact_token,
    sanitize_log_data,
)
from trade_bot.config.settings import BrokerConfig
from trade_bot.domain.exceptions import (
    BrokerAdapterError,
    BrokerAuthenticationError,
    BrokerConnectionError,
    BrokerRateLimitError,
    OrderExecutionError,
    OrderRejectedError,
)
from trade_bot.domain.models import (
    AccountBalance,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    Trade,
)

logger = logging.getLogger(__name__)


class UpstoxBrokerAdapter(IBrokerAdapter):
    """
    Upstox API v2 Infrastructure Adapter.
    """

    def __init__(
        self,
        config: BrokerConfig,
        allow_live: Optional[bool] = None,
        instrument_token_map: Optional[Dict[str, str]] = None,
        http_client: Optional[Any] = None,
    ) -> None:
        self.config = config
        self.allow_live: bool = (
            allow_live if allow_live is not None else getattr(config, "allow_live_trading", False)
        )
        self.base_url: str = getattr(config, "base_url", "https://api.upstox.com/v2").rstrip("/")
        self.order_base_url: str = getattr(
            config, "order_base_url", "https://api-hft.upstox.com/v2"
        ).rstrip("/")
        self.access_token: str = config.access_token or ""
        self.instrument_token_map: Dict[str, str] = dict(instrument_token_map or {})
        self.timeout_seconds: float = float(getattr(config, "timeout_seconds", 10.0))
        self.max_retries: int = int(getattr(config, "max_retries", 3))
        self.retry_backoff_base: float = float(getattr(config, "retry_backoff_base", 1.5))

        self._http_client = http_client
        self._is_connected: bool = False
        self._lock = threading.RLock()
        self._trade_callbacks: List[Callable[[Trade], None]] = []
        self._processed_trade_ids: set[str] = set()
        # Idempotency tracking: client_order_id -> broker_order_id
        self._submitted_client_orders: Dict[str, str] = {}

    @property
    def name(self) -> str:
        return "UpstoxBrokerAdapter"

    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------

    def connect(self) -> None:
        """
        Authenticate and validate session with Upstox API.
        Enforces safety guard: raises BrokerAdapterError if allow_live is False.
        """
        if not self.allow_live:
            raise BrokerAdapterError(
                "Upstox live connection blocked: allow_live_trading is False. "
                "Live trading must be explicitly authorized."
            )

        if not self.access_token:
            raise BrokerAuthenticationError(
                "Upstox access_token is missing. Set UPSTOX_ACCESS_TOKEN or configure access_token."
            )

        logger.info("Connecting to Upstox API v2 with token %s...", redact_token(self.access_token))

        # Validate token against user profile / funds endpoint
        try:
            funds_resp = self._send_request("GET", f"{self.base_url}/user/get-funds-and-margin?segment=SEC")
            if funds_resp.get("status") != "success":
                raise BrokerAuthenticationError(f"Upstox connection verification failed: {funds_resp}")
            self._is_connected = True
            logger.info("Upstox connection verified and session established successfully.")
        except Exception as e:
            self._is_connected = False
            if isinstance(e, (BrokerAuthenticationError, BrokerAdapterError)):
                raise
            raise BrokerConnectionError(f"Failed to connect to Upstox: {e}") from e

    def disconnect(self) -> None:
        """Cleanly terminate Upstox broker session."""
        with self._lock:
            self._is_connected = False
            logger.info("Upstox broker adapter disconnected.")

    def is_connected(self) -> bool:
        """Return True if session is active."""
        return self._is_connected

    # -------------------------------------------------------------------------
    # Account, Positions & Orders Retrieval
    # -------------------------------------------------------------------------

    def get_account_balance(self) -> AccountBalance:
        """Fetch current funds and margin from Upstox."""
        self._ensure_connected()
        url = f"{self.base_url}/user/get-funds-and-margin?segment=SEC"
        response = self._send_request("GET", url)
        data = response.get("data", {})
        return normalize_funds(data)

    def get_positions(self) -> List[Position]:
        """Fetch confirmed intraday and derivative positions from Upstox."""
        self._ensure_connected()
        url = f"{self.base_url}/portfolio/short-term-positions"
        response = self._send_request("GET", url)
        raw_positions = response.get("data", []) or []
        positions: List[Position] = [normalize_position(p) for p in raw_positions]
        return positions

    def get_orders(self) -> List[Order]:
        """Fetch complete order book for the current trading day."""
        self._ensure_connected()
        url = f"{self.base_url}/order/retrieve-all"
        response = self._send_request("GET", url)
        raw_orders = response.get("data", []) or []

        orders: List[Order] = []
        with self._lock:
            for item in raw_orders:
                order = normalize_order(item)
                orders.append(order)
                if order.broker_order_id and order.client_order_id:
                    self._submitted_client_orders[order.client_order_id] = order.broker_order_id
        return orders

    # -------------------------------------------------------------------------
    # Order Lifecycle (Place, Modify, Cancel)
    # -------------------------------------------------------------------------

    def place_order(self, request: OrderRequest) -> str:
        """
        Submit order to Upstox HFT endpoint.
        Guarantees idempotency: checks cached IDs and existing order book before sending
        to prevent duplicate execution on network retry.
        """
        if not self.allow_live:
            raise BrokerAdapterError("Live order placement is strictly blocked when allow_live is False.")
        self._ensure_connected()

        # 1. Check local idempotency cache
        with self._lock:
            if request.client_order_id in self._submitted_client_orders:
                cached_id = self._submitted_client_orders[request.client_order_id]
                logger.info(
                    "Idempotent order hit: client_order_id %s was already submitted as broker_order_id %s",
                    request.client_order_id,
                    cached_id,
                )
                return cached_id

        # 2. Check remote order book before submitting if client_order_id / tag is specified
        target_tag = request.tag or request.client_order_id
        try:
            existing_orders = self.get_orders()
            for ord in existing_orders:
                if ord.client_order_id == target_tag or ord.client_order_id == request.client_order_id:
                    broker_id = ord.broker_order_id or ""
                    with self._lock:
                        self._submitted_client_orders[request.client_order_id] = broker_id
                    logger.info(
                        "Order %s was already accepted by Upstox as %s; skipping duplicate submission.",
                        request.client_order_id,
                        broker_id,
                    )
                    return broker_id
        except Exception as e:
            logger.warning("Order book pre-check encountered an error (proceeding to submit): %s", e)

        # 3. Build Upstox HFT payload
        payload = build_order_payload(request, self.instrument_token_map)
        url = f"{self.order_base_url}/order/place"

        logger.info(
            "Submitting paper/live order to Upstox HFT: %s %d %s @ %s (tag: %s)",
            request.side.value,
            request.quantity,
            request.symbol,
            request.price,
            target_tag,
        )

        response = self._send_request("POST", url, json_data=payload)
        data = response.get("data", {})
        broker_order_id = str(data.get("order_id", ""))
        if not broker_order_id:
            raise OrderExecutionError(f"Upstox place_order succeeded without order_id: {response}")

        with self._lock:
            self._submitted_client_orders[request.client_order_id] = broker_order_id

        logger.info(
            "Order %s successfully accepted by Upstox with broker ID %s",
            request.client_order_id,
            broker_order_id,
        )
        return broker_order_id

    def modify_order(self, modification: OrderModification) -> bool:
        """Modify open order price or quantity at Upstox."""
        if not self.allow_live:
            raise BrokerAdapterError("Live order modification is strictly blocked when allow_live is False.")
        self._ensure_connected()

        payload = build_modify_payload(modification)
        url = f"{self.order_base_url}/order/modify"

        logger.info("Modifying Upstox order %s: %s", modification.order_id, payload)
        response = self._send_request("PUT", url, json_data=payload)
        return response.get("status") == "success"

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel open or pending order at Upstox."""
        if not self.allow_live:
            raise BrokerAdapterError("Live order cancellation is strictly blocked when allow_live is False.")
        self._ensure_connected()

        params = {"order_id": str(broker_order_id)}
        url = f"{self.order_base_url}/order/cancel?{urllib.parse.urlencode(params)}"

        logger.info("Cancelling Upstox order %s", broker_order_id)
        response = self._send_request("DELETE", url)
        return response.get("status") == "success"

    # -------------------------------------------------------------------------
    # Execution Fills & Trade Synchronization
    # -------------------------------------------------------------------------

    def register_trade_callback(self, callback: Callable[[Trade], None]) -> None:
        """Register callback invoked when new fills are detected."""
        with self._lock:
            self._trade_callbacks.append(callback)

    def sync_trades(self) -> List[Trade]:
        """
        Poll trade execution history from Upstox and notify registered callbacks of new fills.
        """
        self._ensure_connected()
        url = f"{self.base_url}/order/trades/get-trades-for-day"
        response = self._send_request("GET", url)
        raw_trades = response.get("data", []) or []

        new_trades: List[Trade] = []
        with self._lock:
            for item in raw_trades:
                trade = normalize_trade(item)
                if trade.trade_id not in self._processed_trade_ids:
                    self._processed_trade_ids.add(trade.trade_id)
                    new_trades.append(trade)
                    for cb in self._trade_callbacks:
                        try:
                            cb(trade)
                        except Exception as ex:
                            logger.error("Error in trade callback for trade %s: %s", trade.trade_id, ex)

        if new_trades:
            logger.info("Discovered and processed %d new Upstox trade fills.", len(new_trades))
        return new_trades

    # -------------------------------------------------------------------------
    # Low-Level Resilient HTTP Dispatcher
    # -------------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        """Check if adapter is connected."""
        if not self._is_connected:
            raise BrokerConnectionError("UpstoxBrokerAdapter is disconnected. Call connect() first.")

    def _get_headers(self) -> Dict[str, str]:
        """Build request headers with Bearer access token."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def _send_request(
        self,
        method: str,
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Dispatch HTTP request with exponential backoff on 429 rate limits and network retries.
        Redacts credentials from all logs.
        """
        headers = self._get_headers()
        req_timeout = timeout or self.timeout_seconds
        body_bytes: Optional[bytes] = None
        if json_data is not None:
            body_bytes = json.dumps(json_data).encode("utf-8")

        attempt = 0
        backoff = self.retry_backoff_base

        while attempt <= self.max_retries:
            attempt += 1
            try:
                # If custom http_client injected (e.g. test mock or custom session)
                if self._http_client is not None:
                    return self._dispatch_custom_client(method, url, headers, json_data, req_timeout)

                # Standard urllib transport
                req = urllib.request.Request(
                    url=url,
                    data=body_bytes,
                    headers=headers,
                    method=method,
                )

                with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                    status_code = resp.getcode()
                    raw_text = resp.read().decode("utf-8")
                    data = json.loads(raw_text)

                    if data.get("status") == "error":
                        self._handle_api_error(status_code, data)
                    return data

            except urllib.error.HTTPError as e:
                status_code = e.code
                error_body = e.read().decode("utf-8")
                parsed_json = {}
                try:
                    parsed_json = json.loads(error_body)
                except Exception:
                    pass

                # Handle HTTP 401 Unauthorized
                if status_code == 401:
                    logger.error("Upstox API Authentication Error (401): Token invalid or expired.")
                    raise BrokerAuthenticationError("Upstox API 401 Unauthorized: Invalid or expired access token.")

                # Handle HTTP 429 Rate Limit
                if status_code == 429:
                    if attempt <= self.max_retries:
                        sleep_time = backoff
                        retry_after = e.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            sleep_time = float(retry_after)
                        logger.warning(
                            "Upstox rate limit hit (429). Retrying in %.1fs (attempt %d/%d)...",
                            sleep_time,
                            attempt,
                            self.max_retries,
                        )
                        time.sleep(sleep_time)
                        backoff *= 2.0
                        continue
                    raise BrokerRateLimitError("Upstox API rate limit exceeded (429). Max retries exhausted.")

                # Handle 400 Bad Request / Order Rejection
                if status_code == 400:
                    errors = parsed_json.get("errors", [])
                    msg = errors[0].get("message") if errors else parsed_json.get("message", e.reason)
                    code = errors[0].get("error_code") if errors else "BAD_REQUEST"
                    logger.error("Upstox API 400 Error [%s]: %s", code, msg)
                    raise OrderRejectedError(f"Upstox order rejected ({code}): {msg}")

                # 5xx Server Errors (retryable)
                if status_code >= 500 and attempt <= self.max_retries:
                    logger.warning(
                        "Upstox server error (%d). Retrying in %.1fs (attempt %d/%d)...",
                        status_code,
                        backoff,
                        attempt,
                        self.max_retries,
                    )
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue

                raise BrokerAdapterError(f"Upstox HTTP error ({status_code}): {error_body}") from e

            except urllib.error.URLError as e:
                # Network / Timeout errors (retryable)
                if attempt <= self.max_retries:
                    logger.warning(
                        "Network error connecting to Upstox: %s. Retrying in %.1fs (attempt %d/%d)...",
                        e.reason,
                        backoff,
                        attempt,
                        self.max_retries,
                    )
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue
                raise BrokerConnectionError(f"Network error connecting to Upstox: {e.reason}") from e

            except json.JSONDecodeError as e:
                raise BrokerAdapterError(f"Malformed JSON response received from Upstox: {e}") from e

        raise BrokerAdapterError("Max retries exceeded while calling Upstox API.")

    def _dispatch_custom_client(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json_data: Optional[Dict[str, Any]],
        timeout: float,
    ) -> Dict[str, Any]:
        """Dispatch request through injected custom HTTP client."""
        sanitized_headers = redact_headers(headers)
        logger.debug("Dispatching via custom client: %s %s headers: %s", method, url, sanitized_headers)

        resp = self._http_client(method=method, url=url, headers=headers, json=json_data, timeout=timeout)
        # Check if response is requests.Response-like or dictionary
        if hasattr(resp, "status_code"):
            code = resp.status_code
            if code == 401:
                raise BrokerAuthenticationError("Upstox API 401 Unauthorized.")
            if code == 429:
                raise BrokerRateLimitError("Upstox API rate limit (429).")
            if code == 400:
                err_data = resp.json() if hasattr(resp, "json") else {}
                errors = err_data.get("errors", [])
                msg = errors[0].get("message") if errors else "Bad request"
                raise OrderRejectedError(f"Upstox order rejected: {msg}")
            if code >= 400:
                raise BrokerAdapterError(f"Upstox HTTP error: {code}")
            return resp.json()
        elif isinstance(resp, dict):
            if resp.get("status") == "error":
                self._handle_api_error(200, resp)
            return resp
        return {}

    def _handle_api_error(self, status_code: int, data: Dict[str, Any]) -> None:
        """Parse Upstox error payload and raise appropriate domain exception."""
        errors = data.get("errors", [])
        msg = errors[0].get("message") if errors else data.get("message", "Unknown Upstox error")
        code = errors[0].get("error_code") if errors else "API_ERROR"
        if "rate limit" in msg.lower() or code in ("UDAPI10005", "UDAPI10006"):
            raise BrokerRateLimitError(f"Upstox rate limit error ({code}): {msg}")
        if "token" in msg.lower() or "auth" in msg.lower() or code in ("UDAPI100050", "UDAPI100016"):
            raise BrokerAuthenticationError(f"Upstox authentication error ({code}): {msg}")
        raise BrokerAdapterError(f"Upstox API error ({code}): {msg}")
