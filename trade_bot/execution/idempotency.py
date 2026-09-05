"""
Idempotency and Deduplication Manager.

Prevents duplicate order submissions caused by network retries, duplicate signals,
or repeated broker execution callbacks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Dict, Optional, Set
from trade_bot.domain.exceptions import DuplicateOrderError
from trade_bot.domain.models import OrderRequest


class IdempotencyManager:
    """
    Tracks client order IDs and deterministic request hashes to enforce idempotent execution.
    """

    def __init__(self, window_seconds: int = 300) -> None:
        self.window_seconds = window_seconds
        self._seen_client_order_ids: Set[str] = set()
        self._request_fingerprints: Dict[str, datetime] = {}

    def compute_fingerprint(self, request: OrderRequest) -> str:
        """Generate a deterministic fingerprint hash for an order request."""
        content = (
            f"{request.symbol}|{request.side.value}|{request.order_type.value}|"
            f"{request.quantity}|{request.price}|{request.trigger_price}|"
            f"{request.strategy_name}|{request.signal_id}"
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def check_and_register(self, request: OrderRequest) -> None:
        """
        Register order request or raise DuplicateOrderError if duplicate is detected.
        """
        now = datetime.now(timezone.utc)

        # Check 1: Explicit client_order_id uniqueness
        if request.client_order_id in self._seen_client_order_ids:
            raise DuplicateOrderError(
                f"Duplicate client_order_id: '{request.client_order_id}' was already submitted",
                context={"client_order_id": request.client_order_id},
            )

        # Check 2: Request payload fingerprint within deduplication window
        fingerprint = self.compute_fingerprint(request)
        if fingerprint in self._request_fingerprints:
            last_seen = self._request_fingerprints[fingerprint]
            if (now - last_seen) < timedelta(seconds=self.window_seconds):
                raise DuplicateOrderError(
                    f"Duplicate order request detected for {request.symbol} {request.side.value} "
                    f"within {self.window_seconds}s window",
                    context={
                        "client_order_id": request.client_order_id,
                        "fingerprint": fingerprint,
                        "last_seen": last_seen.isoformat(),
                    },
                )

        # Register
        self._seen_client_order_ids.add(request.client_order_id)
        self._request_fingerprints[fingerprint] = now

    def is_registered(self, client_order_id: str) -> bool:
        """Check if client_order_id has been registered."""
        return client_order_id in self._seen_client_order_ids
