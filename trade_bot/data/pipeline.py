"""
Real-Time Market Data Ingestion Pipeline.

Provides components for data cleansing, deduplication, out-of-order handling,
stale-data monitoring, and deterministic 5-minute candle aggregation.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import logging

from trade_bot.config.constants import IST_TIMEZONE, MARKET_CLOSE_TIME, MARKET_OPEN_TIME
from trade_bot.data.events import ConnectionStatus, MarketDataEvent, MarketEventType
from trade_bot.domain.models import Candle, Tick

logger = logging.getLogger(__name__)


class DuplicateEventFilter:
    """
    Sliding window deduplication and out-of-order guard for streaming ticks.
    Prevents duplicate ticks from corrupting volume or OHLC calculations,
    and drops retroactive ticks that arrive after a candle window has already closed.
    """

    def __init__(self, max_history: int = 50000) -> None:
        self.max_history = max_history
        self._seen_signatures: Set[Tuple[str, datetime, float, int]] = set()
        self._signature_queue: deque[Tuple[str, datetime, float, int]] = deque()
        self._last_tick_time: Dict[str, datetime] = {}
        self._last_closed_bar_end: Dict[str, datetime] = {}

    def set_last_closed_bar_end(self, symbol: str, end_time: datetime) -> None:
        """Inform the filter that a bar ending at `end_time` has closed."""
        self._last_closed_bar_end[symbol] = end_time

    def is_valid_tick(self, tick: Tick) -> Tuple[bool, Optional[str]]:
        """
        Check if a tick is acceptable.
        Returns: (is_valid, rejection_reason)
        """
        symbol = tick.symbol
        sig = (symbol, tick.timestamp, tick.last_price, tick.volume)

        # 1. Duplicate check
        if sig in self._seen_signatures:
            return False, "DUPLICATE_TICK"

        # 2. Out-of-order check against closed bars
        last_closed = self._last_closed_bar_end.get(symbol)
        if last_closed is not None and tick.timestamp < last_closed:
            return False, "OUT_OF_ORDER_PAST_CLOSED_WINDOW"

        # Track signature in bounded memory
        self._seen_signatures.add(sig)
        self._signature_queue.append(sig)
        if len(self._signature_queue) > self.max_history:
            oldest = self._signature_queue.popleft()
            self._seen_signatures.discard(oldest)

        self._last_tick_time[symbol] = tick.timestamp
        return True, None

    def reset(self) -> None:
        """Clear all deduplication caches."""
        self._seen_signatures.clear()
        self._signature_queue.clear()
        self._last_tick_time.clear()
        self._last_closed_bar_end.clear()


class StaleDataMonitor:
    """
    Health and freshness monitor for real-time market data.
    Tracks elapsed time since last tick per symbol and globally.
    Raises alerts when data becomes stale during active market hours.
    """

    def __init__(self, stale_timeout_seconds: float = 10.0) -> None:
        self.stale_timeout_seconds = stale_timeout_seconds
        self._last_seen_times: Dict[str, datetime] = {}
        self._last_global_seen: Optional[datetime] = None
        self._alert_listeners: List[Callable[[MarketDataEvent], None]] = []

    def register_alert_listener(self, listener: Callable[[MarketDataEvent], None]) -> None:
        """Register callback for stale data alerts."""
        self._alert_listeners.append(listener)

    def record_activity(self, symbol: str, timestamp: datetime) -> None:
        """Record activity for a symbol."""
        self._last_seen_times[symbol] = timestamp
        if self._last_global_seen is None or timestamp > self._last_global_seen:
            self._last_global_seen = timestamp

    def is_stale(self, symbol: str, current_time: datetime) -> bool:
        """Return True if symbol has had no activity exceeding stale_timeout_seconds."""
        last_time = self._last_seen_times.get(symbol)
        if last_time is None:
            return True
        return (current_time - last_time).total_seconds() > self.stale_timeout_seconds

    def check_health(self, current_time: datetime, tracked_symbols: List[str]) -> List[MarketDataEvent]:
        """
        Evaluate staleness across tracked symbols and emit alerts if stale.
        """
        alerts: List[MarketDataEvent] = []
        for sym in tracked_symbols:
            if self.is_stale(sym, current_time):
                last_time = self._last_seen_times.get(sym)
                elapsed = (current_time - last_time).total_seconds() if last_time else float("inf")
                event = MarketDataEvent(
                    event_type=MarketEventType.STALE_DATA_ALERT,
                    timestamp=current_time,
                    symbol=sym,
                    data={"last_seen": last_time, "elapsed_seconds": elapsed},
                )
                alerts.append(event)
                for listener in self._alert_listeners:
                    listener(event)
        return alerts

    def reset(self) -> None:
        self._last_seen_times.clear()
        self._last_global_seen = None


class RealtimeCandleAggregator:
    """
    Deterministic 5-Minute Real-Time Candle Aggregator.
    
    CRITICAL SPECIFICATIONS:
    1. Interval Completion: A candle spanning [T_start, T_end) is NEVER emitted as closed
       until a tick with timestamp >= T_end arrives, or the session is flushed at 15:30.
    2. Timestamp Convention: Every candle's timestamp is the START timestamp of the interval in IST.
       For example, the 09:15 to 09:20 candle has timestamp `09:15:00`.
    3. Missing Ticks Resilience: If ticks are absent for an entire interval, the aggregator does not
       invent phantom bars; the next tick accurately starts a new bar aligned to its epoch interval.
    4. Session Boundaries:
       - Market Open (09:15 IST): Discards or segregates pre-market ticks before 09:15.
       - Market Close (15:30 IST): Immediately finalizes and emits any active forming candle.
    """

    def __init__(
        self,
        timeframe_seconds: int = 300,  # 5 minutes by default
        enforce_market_hours: bool = True,
    ) -> None:
        self.timeframe_seconds = timeframe_seconds
        self.enforce_market_hours = enforce_market_hours
        self._forming_candles: Dict[str, Dict[str, Any]] = {}
        self._candle_handlers: List[Callable[[Candle], None]] = []

    def register_candle_handler(self, handler: Callable[[Candle], None]) -> None:
        """Register callback for completed (closed) candle emissions."""
        self._candle_handlers.append(handler)

    def _get_interval_start(self, dt: datetime) -> datetime:
        """
        Calculate aligned start timestamp of the interval containing `dt`.
        Candle timestamp is the START timestamp of the bar.
        """
        epoch = dt.timestamp()
        bar_epoch = (int(epoch) // self.timeframe_seconds) * self.timeframe_seconds
        return datetime.fromtimestamp(bar_epoch, tz=dt.tzinfo)

    def process_tick(self, tick: Tick) -> Optional[Candle]:
        """
        Process a normalized tick.
        Emits and returns a closed Candle only when the previous bar's time interval is complete.
        """
        symbol = tick.symbol
        tick_time = tick.timestamp

        # Enforce market session boundary if enabled
        if self.enforce_market_hours:
            t = tick_time.time()
            if t < MARKET_OPEN_TIME:
                # Pre-market ticks are ignored for regular 5-minute intraday bars
                return None
            if t >= MARKET_CLOSE_TIME:
                # Post-market ticks
                return None

        bar_start = self._get_interval_start(tick_time)
        closed_candle: Optional[Candle] = None

        if symbol in self._forming_candles:
            current = self._forming_candles[symbol]
            current_bar_start = current["timestamp"]
            current_bar_end = current_bar_start + timedelta(seconds=self.timeframe_seconds)

            if tick_time >= current_bar_end:
                # Interval is complete! Seal and emit the previous candle
                closed_candle = Candle(
                    symbol=symbol,
                    timestamp=current_bar_start,
                    open=current["open"],
                    high=current["high"],
                    low=current["low"],
                    close=current["close"],
                    volume=current["volume"],
                    timeframe_seconds=self.timeframe_seconds,
                    is_closed=True,
                )

                # Initialize new forming bar for this tick
                self._forming_candles[symbol] = {
                    "timestamp": bar_start,
                    "open": tick.last_price,
                    "high": tick.last_price,
                    "low": tick.last_price,
                    "close": tick.last_price,
                    "volume": tick.volume,
                }

                # Dispatch closed candle to subscribers
                for handler in self._candle_handlers:
                    handler(closed_candle)

            else:
                # Tick belongs to the currently forming bar
                current["high"] = max(current["high"], tick.last_price)
                current["low"] = min(current["low"], tick.last_price)
                current["close"] = tick.last_price
                current["volume"] += tick.volume
        else:
            # First tick for symbol: start forming bar
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
        """
        Return an unclosed, forming candle snapshot for streaming/intrabar inspection.
        The candle has `is_closed=False`.
        """
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

    def flush_session(self, symbol: Optional[str] = None) -> List[Candle]:
        """
        Force-close any forming candles at session boundaries (e.g. 15:30:00 market close).
        Returns all sealed candles.
        """
        flushed: List[Candle] = []
        symbols = [symbol] if symbol else list(self._forming_candles.keys())

        for sym in symbols:
            if sym in self._forming_candles:
                current = self._forming_candles.pop(sym)
                candle = Candle(
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
                flushed.append(candle)
                for handler in self._candle_handlers:
                    handler(candle)

        return flushed

    def reset_session(self) -> None:
        """Reset state between trading sessions."""
        self._forming_candles.clear()


class RealtimeMarketDataPipeline:
    """
    End-to-End Real-Time Market Data Ingestion Pipeline.

    Integrates:
    Provider (WebSocket / Mock)
      -> Duplicate & Out-of-Order Filter
      -> Stale Data & Health Monitor
      -> 5-Minute Realtime Candle Aggregator
      -> Normalized Market Event Dispatcher to Strategy/Application Layer
    """

    def __init__(
        self,
        provider: IRealtimeMarketDataProvider,
        candle_aggregator: Optional[RealtimeCandleAggregator] = None,
        duplicate_filter: Optional[DuplicateEventFilter] = None,
        stale_monitor: Optional[StaleDataMonitor] = None,
    ) -> None:
        from trade_bot.data.interfaces import IRealtimeMarketDataProvider

        self.provider = provider
        self.candle_aggregator = candle_aggregator or RealtimeCandleAggregator(timeframe_seconds=300)
        self.duplicate_filter = duplicate_filter or DuplicateEventFilter()
        self.stale_monitor = stale_monitor or StaleDataMonitor()

        self._event_listeners: List[Callable[[MarketDataEvent], None]] = []
        self._candle_listeners: List[Callable[[Candle], None]] = []

        # Wire up provider callbacks
        self.provider.register_event_listener(self._on_provider_event)
        self.candle_aggregator.register_candle_handler(self._on_candle_closed)

    def register_event_listener(self, listener: Callable[[MarketDataEvent], None]) -> None:
        """Register listener for all pipeline events (ticks, candles, alerts, statuses)."""
        self._event_listeners.append(listener)

    def register_candle_listener(self, listener: Callable[[Candle], None]) -> None:
        """Register listener specifically for completed 5-minute candles."""
        self._candle_listeners.append(listener)

    def connect(self) -> None:
        """Start provider connection."""
        self.provider.connect()

    def disconnect(self) -> None:
        """Stop provider connection."""
        self.provider.disconnect()

    def is_connected(self) -> bool:
        """Check provider connection status."""
        return self.provider.is_connected()

    def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to symbols."""
        self.provider.subscribe(symbols)

    def unsubscribe(self, symbols: List[str]) -> None:
        """Unsubscribe from symbols."""
        self.provider.unsubscribe(symbols)

    def get_subscriptions(self) -> Set[str]:
        """Return active subscription symbols."""
        return self.provider.get_subscriptions()

    def get_current_candle(self, symbol: str) -> Optional[Candle]:
        """Return currently forming (unclosed) candle."""
        return self.candle_aggregator.get_current_candle(symbol)

    def check_health(self, current_time: datetime) -> List[MarketDataEvent]:
        """Trigger stale data health check across active subscriptions."""
        alerts = self.stale_monitor.check_health(current_time, list(self.get_subscriptions()))
        for alert in alerts:
            self._dispatch_event(alert)
        return alerts

    def handle_market_open(self, session_date: Optional[datetime] = None) -> MarketDataEvent:
        """Signal market open boundary (09:15 IST)."""
        now = session_date or datetime.now(IST_TIMEZONE)
        self.duplicate_filter.reset()
        self.stale_monitor.reset()
        self.candle_aggregator.reset_session()
        event = MarketDataEvent(
            event_type=MarketEventType.SESSION_OPEN,
            timestamp=now,
            data={"session": "NSE_EQUITY", "open_time": "09:15:00"},
        )
        self._dispatch_event(event)
        return event

    def handle_market_close(self, session_date: Optional[datetime] = None) -> Tuple[MarketDataEvent, List[Candle]]:
        """Signal market close boundary (15:30 IST) and flush forming candles."""
        now = session_date or datetime.now(IST_TIMEZONE)
        flushed_candles = self.candle_aggregator.flush_session()
        event = MarketDataEvent(
            event_type=MarketEventType.SESSION_CLOSE,
            timestamp=now,
            data={"session": "NSE_EQUITY", "close_time": "15:30:00", "flushed_bars": len(flushed_candles)},
        )
        self._dispatch_event(event)
        return event, flushed_candles

    def _on_provider_event(self, event: MarketDataEvent) -> None:
        """Handle raw event dispatched from broker adapter."""
        if event.event_type == MarketEventType.TICK and event.tick:
            tick = event.tick
            # 1. Filter duplicates and out-of-order ticks
            is_valid, reason = self.duplicate_filter.is_valid_tick(tick)
            if not is_valid:
                logger.debug("Rejected tick for %s: %s", tick.symbol, reason)
                return

            # 2. Update stale data monitor
            self.stale_monitor.record_activity(tick.symbol, tick.timestamp)

            # 3. Ingest into 5-minute candle aggregator
            self.candle_aggregator.process_tick(tick)

            # 4. Dispatch valid tick event
            self._dispatch_event(event)
        else:
            # Forward connection status changes, heartbeats, errors
            self._dispatch_event(event)

    def _on_candle_closed(self, candle: Candle) -> None:
        """Handle candle closed emission from aggregator."""
        # Update filter with closed boundary
        bar_end = candle.timestamp + timedelta(seconds=candle.timeframe_seconds)
        self.duplicate_filter.set_last_closed_bar_end(candle.symbol, bar_end)

        # Notify direct candle listeners
        for listener in self._candle_listeners:
            try:
                listener(candle)
            except Exception as e:
                logger.error("Error in candle listener: %s", e)

        # Dispatch normalized CANDLE_CLOSED event
        event = MarketDataEvent(
            event_type=MarketEventType.CANDLE_CLOSED,
            timestamp=bar_end,
            symbol=candle.symbol,
            data=candle,
        )
        self._dispatch_event(event)

    def _dispatch_event(self, event: MarketDataEvent) -> None:
        for listener in self._event_listeners:
            try:
                listener(event)
            except Exception as e:
                logger.error("Error in pipeline event listener: %s", e)

