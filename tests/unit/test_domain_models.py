"""
Unit tests for Domain Models and Invariants.
"""

from datetime import datetime, timezone
import pytest
from trade_bot.domain.enums import OrderSide, OrderType, ProductType
from trade_bot.domain.exceptions import DomainValidationError
from trade_bot.domain.models import Candle, Instrument, OrderRequest, Tick


def test_valid_instrument_creation() -> None:
    inst = Instrument(symbol="INFY", lot_size=1, tick_size=0.05)
    assert inst.symbol == "INFY"
    assert inst.lot_size == 1


def test_invalid_instrument_lot_size() -> None:
    with pytest.raises(DomainValidationError, match="Lot size must be positive"):
        Instrument(symbol="INFY", lot_size=0)


def test_candle_properties() -> None:
    c = Candle(
        symbol="TCS",
        timestamp=datetime(2026, 9, 5, 9, 15, tzinfo=timezone.utc),
        open=3500.0,
        high=3520.0,
        low=3495.0,
        close=3515.0,
        volume=1000,
    )
    assert c.range == 25.0
    assert c.is_bullish is True
    assert c.is_bearish is False


def test_invalid_candle_ohlc_invariants() -> None:
    # High lower than Open
    with pytest.raises(DomainValidationError):
        Candle(
            symbol="TCS",
            timestamp=datetime.now(timezone.utc),
            open=3500.0,
            high=3480.0,
            low=3470.0,
            close=3490.0,
            volume=500,
        )


def test_valid_order_request() -> None:
    req = OrderRequest(
        client_order_id="ORD_101",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=5,
        price=2500.0,
    )
    assert req.client_order_id == "ORD_101"
    assert req.quantity == 5


def test_order_request_limit_requires_price() -> None:
    with pytest.raises(DomainValidationError, match="Price must be positive"):
        OrderRequest(
            client_order_id="ORD_102",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=5,
            price=None,
        )
