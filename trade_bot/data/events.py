"""
Normalized Real-Time Market Data Events and Models.

Defines standardized data models for events emitted by the real-time market-data
pipeline, including streaming ticks, candle closures, session transitions, connection
lifecycle changes, and stale data alerts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from trade_bot.domain.models import Candle, Tick


class ConnectionStatus(str, Enum):
    """Lifecycle connection status for real-time market data feeds."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    STALE = "STALE"
    CLOSED = "CLOSED"


class MarketEventType(str, Enum):
    """Types of market-data events dispatched through the real-time pipeline."""
    TICK = "TICK"
    CANDLE_CLOSED = "CANDLE_CLOSED"
    HEARTBEAT = "HEARTBEAT"
    CONNECTION_STATUS_CHANGED = "CONNECTION_STATUS_CHANGED"
    SESSION_OPEN = "SESSION_OPEN"
    SESSION_CLOSE = "SESSION_CLOSE"
    STALE_DATA_ALERT = "STALE_DATA_ALERT"
    SUBSCRIPTION_CONFIRMED = "SUBSCRIPTION_CONFIRMED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class MarketDataEvent:
    """
    Normalized real-time market data event wrapper.
    Decouples broker-specific WebSocket frames from downstream strategy/risk consumers.
    """
    event_type: MarketEventType
    timestamp: datetime
    symbol: Optional[str] = None
    data: Any = None
    sequence_id: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tick(self) -> Optional[Tick]:
        """Convenience accessor if event wraps a Tick."""
        return self.data if isinstance(self.data, Tick) else None

    @property
    def candle(self) -> Optional[Candle]:
        """Convenience accessor if event wraps a Candle."""
        return self.data if isinstance(self.data, Candle) else None
