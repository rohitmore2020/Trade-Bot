"""
Unit and Integration Test Suite for Upstox Broker Adapter (Phase 19).

Tests all adapter functionalities with mocked Upstox API v2 / HFT responses:
- Safety guards: default allow_live=False blocks real execution
- Authentication & OAuth token exchange
- Token and credential redaction across logs and string representations
- Account balance and funds normalization
- Positions normalization
- Order book normalization across Upstox status enums
- Order placement (Market, Limit, Stop Loss) with Upstox payload schema
- Idempotent order processing: local cache and order book pre-check preventing duplicates
- Order modification and cancellation
- Trade synchronization and fill callbacks
- Error resilience: HTTP 400 rejections, 401 unauthorized, 429 rate limit backoff, network timeouts
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from trade_bot.broker.upstox_adapter import UpstoxBrokerAdapter
from trade_bot.broker.upstox_auth import UpstoxAuthToken, UpstoxOAuthHandler
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
from trade_bot.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
    TimeInForce,
)
from trade_bot.domain.exceptions import (
    BrokerAdapterError,
    BrokerAuthenticationError,
    BrokerConnectionError,
    BrokerRateLimitError,
    OrderRejectedError,
)
from trade_bot.domain.models import OrderModification, OrderRequest


@pytest.fixture
def mock_config() -> BrokerConfig:
    """Fixture providing standard Upstox broker configuration."""
    return BrokerConfig(
        name="UPSTOX",
        api_key="test_api_key",
        api_secret="test_api_secret",
        redirect_uri="https://127.0.0.1:5000/callback",
        access_token="mock_access_token_1234567890",
        base_url="https://api.upstox.com/v2",
        order_base_url="https://api-hft.upstox.com/v2",
        allow_live_trading=True,
        timeout_seconds=5.0,
        max_retries=2,
        retry_backoff_base=0.01,  # Fast backoff for tests
    )


class TestUpstoxSafetyAndRedaction:
    """Verify safety guards and credential redaction."""

    def test_safety_guard_blocks_connection_when_allow_live_false(self):
        """Adapter must refuse to connect if allow_live is False."""
        cfg = BrokerConfig(
            name="UPSTOX",
            access_token="valid_token",
            allow_live_trading=False,
        )
        adapter = UpstoxBrokerAdapter(config=cfg, allow_live=False)
        with pytest.raises(BrokerAdapterError, match="allow_live_trading is False"):
            adapter.connect()

    def test_safety_guard_blocks_orders_when_allow_live_false(self, mock_config: BrokerConfig):
        """Order placement, modification, and cancellation must be blocked if allow_live is False."""
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=False)
        adapter._is_connected = True  # force connected to test operation guard

        req = OrderRequest(
            client_order_id="ORD_001",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        with pytest.raises(BrokerAdapterError, match="strictly blocked"):
            adapter.place_order(req)

        mod = OrderModification(order_id="BK_123", client_order_id="ORD_001", price=2500.0)
        with pytest.raises(BrokerAdapterError, match="strictly blocked"):
            adapter.modify_order(mod)

        with pytest.raises(BrokerAdapterError, match="strictly blocked"):
            adapter.cancel_order("BK_123")

    def test_token_redaction_utilities(self):
        """Verify tokens and sensitive headers are properly masked."""
        raw_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        redacted = redact_token(raw_token)
        assert "eyJh...[REDACTED]" == redacted
        assert raw_token not in redacted

        # Short token
        assert redact_token("short") == "[REDACTED]"
        assert redact_token("") == "[EMPTY]"

        # Redact headers
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {raw_token}",
            "X-Api-Key": "secret_key_value",
        }
        sanitized = redact_headers(headers)
        assert sanitized["Accept"] == "application/json"
        assert raw_token not in sanitized["Authorization"]
        assert sanitized["Authorization"].startswith("Bearer eyJh...[REDACTED]")
        assert "secret_key_value" not in sanitized["X-Api-Key"]

        # Sanitize dictionary
        data = {
            "user": "trader1",
            "access_token": raw_token,
            "nested": {"client_secret": "my_super_secret"},
        }
        clean = sanitize_log_data(data)
        assert clean["user"] == "trader1"
        assert raw_token not in clean["access_token"]
        assert "my_super_secret" not in clean["nested"]["client_secret"]


class TestUpstoxOAuthHandler:
    """Verify OAuth 2.0 authorization URL and token exchange."""

    def test_authorization_url_generation(self):
        handler = UpstoxOAuthHandler(
            api_key="TEST_API_KEY",
            api_secret="TEST_SECRET",
            redirect_uri="https://localhost:8000/callback",
        )
        url = handler.get_authorization_url(state="xyz123")
        assert url.startswith("https://api.upstox.com/v2/login/authorization/dialog")
        assert "client_id=TEST_API_KEY" in url
        assert "redirect_uri=https%3A%2F%2Flocalhost%3A8000%2Fcallback" in url
        assert "state=xyz123" in url

    def test_token_exchange_success(self):
        handler = UpstoxOAuthHandler(
            api_key="TEST_API_KEY",
            api_secret="TEST_SECRET",
            redirect_uri="https://localhost:8000/callback",
        )
        mock_response = {
            "status": "success",
            "data": {
                "access_token": "ACCESS_TOKEN_ABC_123",
                "user_id": "205001",
                "user_name": "John Doe",
                "email": "john@example.com",
            },
        }

        mock_resp_obj = MagicMock()
        mock_resp_obj.getcode.return_value = 200
        mock_resp_obj.read.return_value = json.dumps(mock_response).encode("utf-8")
        mock_resp_obj.__enter__.return_value = mock_resp_obj

        with patch("urllib.request.urlopen", return_value=mock_resp_obj):
            token = handler.exchange_code_for_token("auth_code_999")
            assert token.access_token == "ACCESS_TOKEN_ABC_123"
            assert token.user_id == "205001"
            assert token.user_name == "John Doe"
            assert "ACCESS_TOKEN_ABC_123" not in repr(token)  # token redacted in __repr__


class TestUpstoxModelNormalization:
    """Verify conversion between Upstox schemas and domain models."""

    def test_build_order_payload(self):
        req = OrderRequest(
            client_order_id="ORD_1001",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=25,
            price=2520.50,
            product_type=ProductType.MIS,
            time_in_force=TimeInForce.DAY,
            tag="STRAT_ORB",
        )
        token_map = {"RELIANCE": "NSE_EQ|INE002A01018"}
        payload = build_order_payload(req, token_map)

        assert payload["quantity"] == 25
        assert payload["product"] == "I"  # Intraday
        assert payload["validity"] == "DAY"
        assert payload["price"] == 2520.50
        assert payload["tag"] == "STRAT_ORB"
        assert payload["instrument_token"] == "NSE_EQ|INE002A01018"
        assert payload["order_type"] == "LIMIT"
        assert payload["transaction_type"] == "BUY"

    def test_normalize_order_book_entry(self):
        raw_order = {
            "order_id": "24010800123456",
            "tradingsymbol": "TCS-EQ",
            "product": "I",
            "order_type": "LIMIT",
            "transaction_type": "BUY",
            "price": 3800.0,
            "quantity": 10,
            "status": "complete",
            "filled_quantity": 10,
            "average_price": 3798.5,
            "tag": "ORD_CLIENT_001",
        }
        order = normalize_order(raw_order)
        assert order.broker_order_id == "24010800123456"
        assert order.client_order_id == "ORD_CLIENT_001"
        assert order.symbol == "TCS"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.LIMIT
        assert order.product_type == ProductType.MIS
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 10
        assert order.average_fill_price == 3798.5

    def test_normalize_positions_entry(self):
        raw_pos = {
            "tradingsymbol": "INFY-EQ",
            "product": "I",
            "quantity": 50,
            "average_price": 1500.0,
            "last_price": 1520.0,
            "realised": 250.0,
            "unrealised": 1000.0,
        }
        pos = normalize_position(raw_pos)
        assert pos.symbol == "INFY"
        assert pos.product_type == ProductType.MIS
        assert pos.quantity == 50
        assert pos.average_price == 1500.0
        assert pos.last_price == 1520.0
        assert pos.realized_pnl == 250.0
        assert pos.unrealized_pnl == 1000.0

    def test_normalize_trade_entry(self):
        raw_trade = {
            "trade_id": "TRD_998877",
            "order_id": "24010800123456",
            "order_ref_id": "CLIENT_REF_01",
            "tradingsymbol": "RELIANCE-EQ",
            "transaction_type": "SELL",
            "quantity": 15,
            "average_price": 2515.0,
            "exchange": "NSE",
            "exchange_timestamp": "2024-01-08 11:20:00",
        }
        trade = normalize_trade(raw_trade)
        assert trade.trade_id == "TRD_998877"
        assert trade.order_id == "24010800123456"
        assert trade.client_order_id == "CLIENT_REF_01"
        assert trade.symbol == "RELIANCE"
        assert trade.side == OrderSide.SELL
        assert trade.quantity == 15
        assert trade.price == 2515.0
        assert trade.exchange == "NSE"

    def test_normalize_funds_entry(self):
        raw_funds = {
            "equity": {
                "available_margin": 150000.0,
                "used_margin": 25000.0,
                "payin_amount": 5000.0,
            }
        }
        balance = normalize_funds(raw_funds)
        assert balance.available_cash == 150000.0
        assert balance.used_margin == 25000.0
        assert balance.initial_capital == 175000.0
        assert balance.total_equity == 175000.0


class TestUpstoxBrokerAdapterOperations:
    """Test full operations of UpstoxBrokerAdapter with mocked HTTP responses."""

    def test_connect_and_disconnect(self, mock_config: BrokerConfig):
        """Verify successful connection and graceful disconnection."""
        mock_client = MagicMock()
        mock_client.return_value = {
            "status": "success",
            "data": {"equity": {"available_margin": 100000.0, "used_margin": 0.0}},
        }

        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        assert adapter.is_connected() is False
        adapter.connect()
        assert adapter.is_connected() is True

        adapter.disconnect()
        assert adapter.is_connected() is False

    def test_get_account_balance(self, mock_config: BrokerConfig):
        """Verify funds retrieval and mapping to AccountBalance."""
        mock_client = MagicMock()
        mock_client.return_value = {
            "status": "success",
            "data": {
                "equity": {
                    "available_margin": 85000.50,
                    "used_margin": 15000.0,
                    "payin_amount": 0.0,
                }
            },
        }
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        balance = adapter.get_account_balance()
        assert balance.available_cash == 85000.50
        assert balance.used_margin == 15000.0
        assert balance.total_equity == 100000.50

    def test_get_positions(self, mock_config: BrokerConfig):
        """Verify positions retrieval and mapping to domain models."""
        mock_client = MagicMock()
        mock_client.return_value = {
            "status": "success",
            "data": [
                {
                    "tradingsymbol": "RELIANCE-EQ",
                    "product": "I",
                    "quantity": 10,
                    "average_price": 2500.0,
                    "last_price": 2510.0,
                    "realised": 0.0,
                    "unrealised": 100.0,
                },
                {
                    "tradingsymbol": "TCS-EQ",
                    "product": "I",
                    "quantity": 0,
                    "average_price": 3800.0,
                    "last_price": 3820.0,
                    "realised": 500.0,
                    "unrealised": 0.0,
                },
            ],
        }
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        positions = adapter.get_positions()
        assert len(positions) == 2
        assert positions[0].symbol == "RELIANCE"
        assert positions[0].quantity == 10
        assert positions[0].unrealized_pnl == 100.0
        assert positions[1].symbol == "TCS"
        assert positions[1].is_flat is True
        assert positions[1].realized_pnl == 500.0

    def test_get_orders(self, mock_config: BrokerConfig):
        """Verify order book retrieval and status normalization."""
        mock_client = MagicMock()
        mock_client.return_value = {
            "status": "success",
            "data": [
                {
                    "order_id": "ORD_B1",
                    "tradingsymbol": "RELIANCE-EQ",
                    "quantity": 10,
                    "price": 2500.0,
                    "status": "complete",
                    "filled_quantity": 10,
                    "tag": "CLIENT_01",
                },
                {
                    "order_id": "ORD_B2",
                    "tradingsymbol": "INFY-EQ",
                    "quantity": 20,
                    "price": 1500.0,
                    "status": "open",
                    "filled_quantity": 0,
                    "tag": "CLIENT_02",
                },
                {
                    "order_id": "ORD_B3",
                    "tradingsymbol": "TCS-EQ",
                    "quantity": 5,
                    "price": 3800.0,
                    "status": "rejected",
                    "status_message": "RMS: Margin Insufficient",
                    "tag": "CLIENT_03",
                },
            ],
        }
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        orders = adapter.get_orders()
        assert len(orders) == 3
        assert orders[0].status == OrderStatus.FILLED
        assert orders[1].status == OrderStatus.ACKNOWLEDGED
        assert orders[2].status == OrderStatus.REJECTED
        assert orders[2].rejection_reason == "RMS: Margin Insufficient"

    def test_place_order_success(self, mock_config: BrokerConfig):
        """Verify place order submits to HFT endpoint and returns broker order ID."""
        mock_client = MagicMock()
        # First call: get_orders() check returns empty
        # Second call: POST /order/place returns order_id
        mock_client.side_effect = [
            {"status": "success", "data": []},  # order book check
            {"status": "success", "data": {"order_id": "24010800099999"}},  # place order
        ]
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        req = OrderRequest(
            client_order_id="ORD_PLACE_1",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=15,
            product_type=ProductType.MIS,
        )
        broker_id = adapter.place_order(req)
        assert broker_id == "24010800099999"

        # Check call arguments
        place_call = mock_client.call_args_list[1]
        assert place_call.kwargs["method"] == "POST"
        assert place_call.kwargs["url"] == "https://api-hft.upstox.com/v2/order/place"
        assert place_call.kwargs["json"]["quantity"] == 15
        assert place_call.kwargs["json"]["product"] == "I"

    def test_idempotent_order_submission_local_cache(self, mock_config: BrokerConfig):
        """Duplicate submission with same client_order_id returns cached broker ID without new request."""
        mock_client = MagicMock()
        mock_client.side_effect = [
            {"status": "success", "data": []},
            {"status": "success", "data": {"order_id": "24010800099999"}},
        ]
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        req = OrderRequest(
            client_order_id="ORD_IDEM_1",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=15,
        )
        id1 = adapter.place_order(req)
        assert id1 == "24010800099999"

        # Second call with same client_order_id
        id2 = adapter.place_order(req)
        assert id2 == "24010800099999"
        # Total calls should still be 2 (initial check + initial post), no 3rd call made
        assert mock_client.call_count == 2

    def test_idempotent_order_submission_remote_check(self, mock_config: BrokerConfig):
        """If order already accepted by broker, pre-check prevents duplicate submission."""
        mock_client = MagicMock()
        # Order book check shows order already present
        mock_client.return_value = {
            "status": "success",
            "data": [
                {
                    "order_id": "BK_ALREADY_EXISTS_888",
                    "tradingsymbol": "RELIANCE-EQ",
                    "tag": "ORD_RETRY_1",
                }
            ],
        }
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        req = OrderRequest(
            client_order_id="ORD_RETRY_1",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=15,
        )
        broker_id = adapter.place_order(req)
        assert broker_id == "BK_ALREADY_EXISTS_888"
        # Only 1 call was made (GET /order/retrieve-all), POST /order/place was NOT called
        assert mock_client.call_count == 1
        assert mock_client.call_args.kwargs["method"] == "GET"

    def test_modify_order_success(self, mock_config: BrokerConfig):
        mock_client = MagicMock()
        mock_client.return_value = {"status": "success", "data": {"order_id": "ORD_M1"}}
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        mod = OrderModification(
            order_id="ORD_M1",
            client_order_id="CLIENT_M1",
            price=2515.0,
            quantity=20,
        )
        assert adapter.modify_order(mod) is True
        call_kwargs = mock_client.call_args.kwargs
        assert call_kwargs["method"] == "PUT"
        assert call_kwargs["url"] == "https://api-hft.upstox.com/v2/order/modify"
        assert call_kwargs["json"]["order_id"] == "ORD_M1"
        assert call_kwargs["json"]["price"] == 2515.0

    def test_cancel_order_success(self, mock_config: BrokerConfig):
        mock_client = MagicMock()
        mock_client.return_value = {"status": "success", "data": {"order_id": "ORD_C1"}}
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        assert adapter.cancel_order("ORD_C1") is True
        call_kwargs = mock_client.call_args.kwargs
        assert call_kwargs["method"] == "DELETE"
        assert "order_id=ORD_C1" in call_kwargs["url"]

    def test_sync_trades_and_callback_dispatch(self, mock_config: BrokerConfig):
        mock_client = MagicMock()
        mock_client.return_value = {
            "status": "success",
            "data": [
                {
                    "trade_id": "T_01",
                    "order_id": "O_01",
                    "tradingsymbol": "RELIANCE-EQ",
                    "transaction_type": "BUY",
                    "quantity": 10,
                    "average_price": 2500.0,
                },
                {
                    "trade_id": "T_02",
                    "order_id": "O_02",
                    "tradingsymbol": "TCS-EQ",
                    "transaction_type": "SELL",
                    "quantity": 5,
                    "average_price": 3800.0,
                },
            ],
        }
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        received_trades = []
        adapter.register_trade_callback(lambda t: received_trades.append(t))

        trades = adapter.sync_trades()
        assert len(trades) == 2
        assert len(received_trades) == 2
        assert received_trades[0].trade_id == "T_01"
        assert received_trades[1].trade_id == "T_02"

        # Second sync: previously processed trade IDs are ignored to prevent duplicates
        new_trades = adapter.sync_trades()
        assert len(new_trades) == 0
        assert len(received_trades) == 2


class TestUpstoxErrorResilience:
    """Test error handling, status code translation, and rate limit backoff."""

    def test_http_401_unauthorized_raises_authentication_error(self, mock_config: BrokerConfig):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_client.return_value = mock_resp

        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        with pytest.raises(BrokerAuthenticationError, match="401 Unauthorized"):
            adapter.get_account_balance()

    def test_http_400_bad_request_raises_order_rejected_error(self, mock_config: BrokerConfig):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "status": "error",
            "errors": [{"error_code": "UDAPI100010", "message": "Circuit Limit Breached"}],
        }
        mock_client.return_value = mock_resp

        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        req = OrderRequest(
            client_order_id="ORD_ERR",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        # Pre-check returns empty order book, then place order fails with 400
        mock_client.side_effect = [
            {"status": "success", "data": []},
            mock_resp,
        ]
        with pytest.raises(OrderRejectedError, match="Circuit Limit Breached"):
            adapter.place_order(req)

    def test_http_429_rate_limit_exceeded_raises_rate_limit_error(self, mock_config: BrokerConfig):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_client.return_value = mock_resp

        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True, http_client=mock_client)
        adapter._is_connected = True

        with pytest.raises(BrokerRateLimitError, match="rate limit"):
            adapter.get_account_balance()

    def test_disconnected_adapter_raises_broker_connection_error(self, mock_config: BrokerConfig):
        adapter = UpstoxBrokerAdapter(config=mock_config, allow_live=True)
        assert adapter.is_connected() is False

        with pytest.raises(BrokerConnectionError, match="disconnected"):
            adapter.get_account_balance()

        with pytest.raises(BrokerConnectionError, match="disconnected"):
            adapter.get_positions()

        with pytest.raises(BrokerConnectionError, match="disconnected"):
            adapter.get_orders()
