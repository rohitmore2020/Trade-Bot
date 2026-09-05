"""
Pure Signal and TradeIntent Construction.

Constructs strongly typed TradeIntent objects containing all required metadata
for downstream risk management and execution layers.

Zero external infrastructure dependencies; pure domain logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import Instrument
from trade_bot.strategy.models import TradeIntent


class SignalBuilder:
    """
    Pure builder for constructing immutable TradeIntent objects.
    """

    @staticmethod
    def build_entry_intent(
        strategy_version: str,
        timestamp: datetime,
        instrument: Instrument,
        side: OrderSide,
        signal_price: float,
        proposed_entry_price: float,
        proposed_stop_price: float,
        atr: float,
        vwap: float,
        or_high: float,
        or_low: float,
        volume_ratio: float,
        signal_reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeIntent:
        return TradeIntent(
            strategy_version=strategy_version,
            timestamp=timestamp,
            instrument=instrument,
            side=side,
            signal_price=round(signal_price, 2),
            proposed_entry_price=round(proposed_entry_price, 2),
            proposed_stop_price=round(proposed_stop_price, 2),
            atr=round(atr, 4),
            vwap=round(vwap, 2),
            or_high=round(or_high, 2),
            or_low=round(or_low, 2),
            volume_ratio=round(volume_ratio, 2),
            signal_reason=signal_reason,
            intent_type="ENTRY",
            metadata=metadata or {},
        )

    @staticmethod
    def build_exit_intent(
        strategy_version: str,
        timestamp: datetime,
        instrument: Instrument,
        side: OrderSide,
        exit_price: float,
        stop_price: float,
        atr: float,
        vwap: float,
        or_high: float,
        or_low: float,
        volume_ratio: float,
        exit_reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeIntent:
        return TradeIntent(
            strategy_version=strategy_version,
            timestamp=timestamp,
            instrument=instrument,
            side=side,
            signal_price=round(exit_price, 2),
            proposed_entry_price=round(exit_price, 2),
            proposed_stop_price=round(stop_price, 2),
            atr=round(atr, 4),
            vwap=round(vwap, 2),
            or_high=round(or_high, 2),
            or_low=round(or_low, 2),
            volume_ratio=round(volume_ratio, 2),
            signal_reason=exit_reason,
            intent_type="EXIT",
            metadata=metadata or {},
        )
