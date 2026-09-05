"""
Candle Aggregator.

Aggregates continuous streaming ticks into deterministic OHLCV candles
across arbitrary timeframes (e.g., 1-minute, 5-minute, 15-minute).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from trade_bot.domain.models import Candle, Tick


class TimeframeCandleAggregator:
    """
    Maintains active forming candles and emits completed candles when time intervals elapse.
    """

    def __init__(self, timeframe_seconds: int = 60) -> None:
        self.timeframe_seconds = timeframe_seconds
        self._forming_candles: Dict[str, Dict[str, Any]] = {}
        self._candle_handlers: List[Callable[[Candle], None]] = []

    def register_candle_handler(self, handler: Callable[[Candle], None]) -> None:
        """Register a callback invoked whenever a candle closes."""
        self._candle_handlers.append(handler)

    def _get_bar_timestamp(self, tick_time: datetime) -> datetime:
        """Calculate the start timestamp of the bar containing this tick."""
        epoch = tick_time.timestamp()
        bar_epoch = (epoch // self.timeframe_seconds) * self.timeframe_seconds
        return datetime.fromtimestamp(bar_epoch, tz=tick_time.tzinfo)

    def process_tick(self, tick: Tick) -> Optional[Candle]:
        """
        Ingest a tick. If the tick belongs to a new time window, the previous candle
        is closed, emitted to listeners, and returned.
        """
        symbol = tick.symbol
        bar_start = self._get_bar_timestamp(tick.timestamp)
        closed_candle: Optional[Candle] = None

        if symbol in self._forming_candles:
            current = self._forming_candles[symbol]
            if bar_start > current["timestamp"]:
                # Current bar has finished
                closed_candle = Candle(
                    symbol=symbol,
                    timestamp=current["timestamp"],
                    open=current["open"],
                    high=current["high"],
                    low=current["low"],
                    close=current["close"],
                    volume=current["volume"],
                    timeframe_seconds=self.timeframe_seconds,
                    is_closed=True,
                )
                # Reset for new bar
                self._forming_candles[symbol] = {
                    "timestamp": bar_start,
                    "open": tick.last_price,
                    "high": tick.last_price,
                    "low": tick.last_price,
                    "close": tick.last_price,
                    "volume": tick.volume,
                }
                # Emit to handlers
                for handler in self._candle_handlers:
                    handler(closed_candle)
            else:
                # Update current bar
                current["high"] = max(current["high"], tick.last_price)
                current["low"] = min(current["low"], tick.last_price)
                current["close"] = tick.last_price
                current["volume"] += tick.volume
        else:
            # First tick for this symbol
            self._forming_candles[symbol] = {
                "timestamp": bar_start,
                "open": tick.last_price,
                "high": tick.last_price,
                "low": tick.last_price,
                "close": tick.last_price,
                "volume": tick.volume,
            }

        return closed_candle

    def get_current_candle(self, symbol: str) -> Optional[Candle]:
        """Get the current unclosed candle snapshot for a symbol."""
        if symbol not in self._forming_candles:
            return None
        current = self._forming_candles[symbol]
        return Candle(
            symbol=symbol,
            timestamp=current["timestamp"],
            open=current["open"],
            high=current["high"],
            low=current["low"],
            close=current["close"],
            volume=current["volume"],
            timeframe_seconds=self.timeframe_seconds,
            is_closed=False,
        )

    def flush(self, symbol: Optional[str] = None) -> List[Candle]:
        """Force close and return active forming candles (e.g. at end of day)."""
        flushed: List[Candle] = []
        symbols = [symbol] if symbol else list(self._forming_candles.keys())
        for sym in symbols:
            if sym in self._forming_candles:
                current = self._forming_candles.pop(sym)
                c = Candle(
                    symbol=sym,
                    timestamp=current["timestamp"],
                    open=current["open"],
                    high=current["high"],
                    low=current["low"],
                    close=current["close"],
                    volume=current["volume"],
                    timeframe_seconds=self.timeframe_seconds,
                    is_closed=True,
                )
                flushed.append(c)
                for handler in self._candle_handlers:
                    handler(c)
        return flushed
