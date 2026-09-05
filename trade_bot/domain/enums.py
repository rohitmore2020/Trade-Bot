"""
Domain Enums for Financial Entities, Order Lifecycles, and Trading Types.
"""

from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL_MARKET = "SL_MARKET"
    SL_LIMIT = "SL_LIMIT"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ProductType(str, Enum):
    MIS = "MIS"  # Margin Intraday Square-off (NSE intraday)
    CNC = "CNC"  # Cash and Carry (Delivery)
    NRML = "NRML"  # Normal (F&O / Margin)


class TimeInForce(str, Enum):
    DAY = "DAY"
    IOC = "IOC"  # Immediate or Cancel
    GTC = "GTC"  # Good Till Cancelled


class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    INDEX = "INDEX"
    FUTURE = "FUTURE"
    OPTION = "OPTION"


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class RiskCheckResultStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"


class TradingSessionStatus(str, Enum):
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    ORB_ACTIVE = "ORB_ACTIVE"
    NO_NEW_ENTRIES = "NO_NEW_ENTRIES"
    SQUARE_OFF = "SQUARE_OFF"
    CLOSED = "CLOSED"


class MarketRegime(str, Enum):
    """Benchmark market regime determined by index relative to VWAP."""
    BULLISH = "BULLISH"  # Index > VWAP -> Long only
    BEARISH = "BEARISH"  # Index < VWAP -> Short only
    NEUTRAL = "NEUTRAL"  # Index == VWAP -> No trades
