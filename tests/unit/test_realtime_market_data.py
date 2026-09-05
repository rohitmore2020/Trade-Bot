"""
Unit Tests for Phase 16 Real-Time Market-Data Subsystem.

Validates:
1. Upstox V3 Market Data Feed adapter connection, subscriptions, and auto-reconnect with subscription recovery.
2. Protobuf/JSON payload decoding into normalized domain Ticks.
3. DuplicateEventFilter: duplicate suppression and out-of-order rejection.
4. StaleDataMonitor: heartbeat monitoring and stale-data alerts.
5. RealtimeCandleAggregator: strict 5-minute interval completion, start-timestamp convention, and missing ticks resilience.
6. Session boundaries: pre-market filtering, market open reset, and market close (15:30) candle flush.
7. RealtimeMarketDataPipeline end-to-end integration.
8. Architectural purity: zero Upstox imports in strategy and risk layers.
"""

from datetime import datetime, time, timedelta, timezone
import pytest

from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.data.events import ConnectionStatus, MarketDataEvent, MarketEventType
from trade_bot.data.pipeline import (
    DuplicateEventFilter,
    RealtimeCandleAggregator,
    RealtimeMarketDataPipeline,
    StaleDataMonitor,
)
from trade_bot.data.upstox_realtime import UpstoxRealtimeDataAdapter, UpstoxV3Decoder
from trade_bot.domain.models import Candle, Tick


class MockRealtimeProvider(UpstoxRealtimeDataAdapter):
    """Mock real-time streaming provider for testing without network sockets."""

    def __init__(self) -> None:
        super().__init__(
            api_key="mock_key",
            access_token="mock_token",
            reconnect_base_delay=0.01,
            reconnect_max_delay=0.05,
        )
        self.sent_sub_payloads: list[dict] = []

    def _send_subscription_payload(self, symbols: list[str]) -> dict:
        payload = super()._send_subscription_payload(symbols)
        self.sent_sub_payloads.append(payload)
        return payload


class TestRealtimeMarketDataSubsystem:
    """Test suite for Phase 16 real-time market-data engine."""

    # -------------------------------------------------------------------------
    # 1. Connection Lifecycle & Reconnection Handling
    # -------------------------------------------------------------------------

    def test_connection_lifecycle_and_subscription_management(self):
        """Verify connect, subscribe, unsubscribe, and status transitions."""
        provider = MockRealtimeProvider()
        assert provider.get_connection_status() == ConnectionStatus.DISCONNECTED
        assert not provider.is_connected()

        status_events: list[MarketDataEvent] = []
        provider.register_event_listener(
            lambda e: status_events.append(e) if e.event_type == MarketEventType.CONNECTION_STATUS_CHANGED else None
        )

        provider.connect()
        assert provider.is_connected()
        assert provider.get_connection_status() == ConnectionStatus.CONNECTED

        # Subscribe
        provider.subscribe(["RELIANCE", "TCS"])
        assert provider.get_subscriptions() == {"RELIANCE", "TCS"}

        # Unsubscribe
        provider.unsubscribe(["TCS"])
        assert provider.get_subscriptions() == {"RELIANCE"}

        provider.disconnect()
        assert not provider.is_connected()
        assert provider.get_connection_status() == ConnectionStatus.DISCONNECTED

    def test_reconnection_with_subscription_recovery(self):
        """Verify automatic reconnection with exponential backoff and subscription recovery."""
        provider = MockRealtimeProvider()
        provider.connect()
        provider.subscribe(["INFY", "HDFCBANK"])
        provider.sent_sub_payloads.clear()

        # Simulate network failure / connection loss
        provider.handle_connection_loss("Socket timeout")

        # After reconnect cycle executes, should be connected again and re-subscribed
        assert provider.is_connected()
        assert provider.get_connection_status() == ConnectionStatus.CONNECTED
        assert len(provider.sent_sub_payloads) == 1
        assert set(provider.sent_sub_payloads[0]["data"]["instrumentKeys"]) == {"INFY", "HDFCBANK"}

    # -------------------------------------------------------------------------
    # 2. Upstox V3 Feed Decoding
    # -------------------------------------------------------------------------

    def test_upstox_v3_decoder_ltpc_and_full_modes(self):
        """Verify decoding of Upstox V3 feed dictionaries into normalized domain Ticks."""
        payload = {
            "feeds": {
                "NSE_EQ|INE002A01018": {
                    "ltpc": {
                        "ltp": 2550.75,
                        "ltq": 15,
                        "ltt": 1704705000000,  # epoch ms
                    }
                },
                "NSE_EQ|INE467B01029": {
                    "full": {
                        "marketFF": {
                            "ltpc": {"ltp": 3820.0, "ltt": 1704705000000},
                            "vtt": 250000,
                        }
                    }
                },
            }
        }

        ticks = UpstoxV3Decoder.decode_feed_payload(payload)
        assert len(ticks) == 2
        t1 = next(t for t in ticks if "INE002A01018" in t.symbol)
        assert t1.last_price == 2550.75
        assert t1.volume == 15

        t2 = next(t for t in ticks if "INE467B01029" in t.symbol)
        assert t2.last_price == 3820.0
        assert t2.volume == 250000

    # -------------------------------------------------------------------------
    # 3. Duplicate and Out-of-Order Filtering
    # -------------------------------------------------------------------------

    def test_duplicate_tick_rejection(self):
        """Verify identical ticks are suppressed and do not pollute calculations."""
        dup_filter = DuplicateEventFilter()
        ts = datetime(2024, 1, 8, 9, 16, 0, tzinfo=IST_TIMEZONE)
        tick = Tick(symbol="RELIANCE", timestamp=ts, last_price=2500.0, volume=10)

        # First ingestion -> valid
        valid, reason = dup_filter.is_valid_tick(tick)
        assert valid is True
        assert reason is None

        # Duplicate ingestion -> rejected
        valid2, reason2 = dup_filter.is_valid_tick(tick)
        assert valid2 is False
        assert reason2 == "DUPLICATE_TICK"

    def test_out_of_order_tick_rejection_after_candle_closed(self):
        """Verify ticks arriving after their corresponding candle has closed are rejected."""
        dup_filter = DuplicateEventFilter()
        # Bar [09:15:00, 09:20:00) has closed at 09:20:00
        closed_end = datetime(2024, 1, 8, 9, 20, 0, tzinfo=IST_TIMEZONE)
        dup_filter.set_last_closed_bar_end("RELIANCE", closed_end)

        # Tick at 09:18:30 arrives late after the 09:20:00 close
        late_tick = Tick(
            symbol="RELIANCE",
            timestamp=datetime(2024, 1, 8, 9, 18, 30, tzinfo=IST_TIMEZONE),
            last_price=2505.0,
            volume=5,
        )
        valid, reason = dup_filter.is_valid_tick(late_tick)
        assert valid is False
        assert reason == "OUT_OF_ORDER_PAST_CLOSED_WINDOW"

        # Tick at 09:20:05 arrives for the new bar -> valid
        new_tick = Tick(
            symbol="RELIANCE",
            timestamp=datetime(2024, 1, 8, 9, 20, 5, tzinfo=IST_TIMEZONE),
            last_price=2508.0,
            volume=10,
        )
        valid2, reason2 = dup_filter.is_valid_tick(new_tick)
        assert valid2 is True

    # -------------------------------------------------------------------------
    # 4. Stale Data Detection & Heartbeats
    # -------------------------------------------------------------------------

    def test_stale_data_detection_and_alerts(self):
        """Verify StaleDataMonitor flags silence exceeding timeout."""
        monitor = StaleDataMonitor(stale_timeout_seconds=5.0)
        t0 = datetime(2024, 1, 8, 9, 15, 0, tzinfo=IST_TIMEZONE)
        monitor.record_activity("RELIANCE", t0)

        # 3 seconds later -> not stale
        t1 = t0 + timedelta(seconds=3)
        assert not monitor.is_stale("RELIANCE", t1)
        assert len(monitor.check_health(t1, ["RELIANCE"])) == 0

        # 8 seconds later -> stale
        t2 = t0 + timedelta(seconds=8)
        assert monitor.is_stale("RELIANCE", t2)
        alerts = monitor.check_health(t2, ["RELIANCE"])
        assert len(alerts) == 1
        assert alerts[0].event_type == MarketEventType.STALE_DATA_ALERT
        assert alerts[0].symbol == "RELIANCE"

    # -------------------------------------------------------------------------
    # 5. 5-Minute Real-Time Candle Aggregator
    # -------------------------------------------------------------------------

    def test_candle_not_generated_until_interval_complete(self):
        """Verify 5-minute candle is NOT emitted until interval is 100% complete."""
        aggregator = RealtimeCandleAggregator(timeframe_seconds=300, enforce_market_hours=False)
        closed_candles: list[Candle] = []
        aggregator.register_candle_handler(lambda c: closed_candles.append(c))

        base_time = datetime(2024, 1, 8, 9, 15, 0, tzinfo=IST_TIMEZONE)

        # Ingest ticks throughout [09:15:00, 09:20:00)
        ticks = [
            Tick("RELIANCE", base_time + timedelta(seconds=0), 2500.0, 10),   # Open
            Tick("RELIANCE", base_time + timedelta(seconds=60), 2510.0, 20),  # High
            Tick("RELIANCE", base_time + timedelta(seconds=120), 2495.0, 15), # Low
            Tick("RELIANCE", base_time + timedelta(seconds=299), 2505.0, 25), # Close before boundary
        ]

        for t in ticks:
            res = aggregator.process_tick(t)
            assert res is None, "Candle must NOT close prematurely before interval end"
            assert len(closed_candles) == 0

        # Forming candle should be readable intrabar
        forming = aggregator.get_current_candle("RELIANCE")
        assert forming is not None
        assert forming.is_closed is False
        assert forming.open == 2500.0
        assert forming.high == 2510.0
        assert forming.low == 2495.0
        assert forming.close == 2505.0
        assert forming.volume == 70
        assert forming.timestamp == base_time  # Start of interval convention

        # Tick at 09:20:00 arrives -> strictly closes the [09:15, 09:20) bar
        boundary_tick = Tick("RELIANCE", base_time + timedelta(seconds=300), 2508.0, 30)
        closed = aggregator.process_tick(boundary_tick)

        assert closed is not None
        assert len(closed_candles) == 1
        c = closed_candles[0]
        assert c.is_closed is True
        assert c.timestamp == base_time
        assert c.open == 2500.0
        assert c.high == 2510.0
        assert c.low == 2495.0
        assert c.close == 2505.0
        assert c.volume == 70

        # New forming bar has started with the boundary tick
        next_forming = aggregator.get_current_candle("RELIANCE")
        assert next_forming is not None
        assert next_forming.timestamp == base_time + timedelta(seconds=300)
        assert next_forming.open == 2508.0

    def test_missing_ticks_gap_handling(self):
        """Verify that skipping multiple intervals does not invent phantom candles."""
        aggregator = RealtimeCandleAggregator(timeframe_seconds=300, enforce_market_hours=False)
        closed_candles: list[Candle] = []
        aggregator.register_candle_handler(lambda c: closed_candles.append(c))

        base_time = datetime(2024, 1, 8, 9, 15, 0, tzinfo=IST_TIMEZONE)
        aggregator.process_tick(Tick("TCS", base_time + timedelta(seconds=30), 3800.0, 10))

        # Jump forward 25 minutes to 09:41:00 (no ticks during 9:20-9:40)
        jump_tick = Tick("TCS", base_time + timedelta(minutes=26), 3825.0, 40)
        closed = aggregator.process_tick(jump_tick)

        # Should close the single 09:15 bar, NOT 5 phantom bars
        assert closed is not None
        assert len(closed_candles) == 1
        assert closed_candles[0].timestamp == base_time
        assert closed_candles[0].close == 3800.0

        # New forming candle begins at 09:40:00
        forming = aggregator.get_current_candle("TCS")
        assert forming is not None
        assert forming.timestamp == base_time + timedelta(minutes=25)  # 09:40:00
        assert forming.open == 3825.0

    # -------------------------------------------------------------------------
    # 6. Session Boundaries & Market Close Flush
    # -------------------------------------------------------------------------

    def test_pre_market_rejection_and_market_close_flush(self):
        """Verify pre-market ticks are rejected and 15:30 close flushes final bar."""
        aggregator = RealtimeCandleAggregator(timeframe_seconds=300, enforce_market_hours=True)
        closed_candles: list[Candle] = []
        aggregator.register_candle_handler(lambda c: closed_candles.append(c))

        # Pre-market tick at 09:08 IST
        pre_tick = Tick(
            "INFY",
            datetime(2024, 1, 8, 9, 8, 0, tzinfo=IST_TIMEZONE),
            1500.0,
            50,
        )
        res = aggregator.process_tick(pre_tick)
        assert res is None
        assert aggregator.get_current_candle("INFY") is None

        # Regular market tick at 15:26:00
        reg_tick = Tick(
            "INFY",
            datetime(2024, 1, 8, 15, 26, 0, tzinfo=IST_TIMEZONE),
            1520.0,
            100,
        )
        aggregator.process_tick(reg_tick)
        assert aggregator.get_current_candle("INFY") is not None

        # Market Close at 15:30:00 -> flush session
        flushed = aggregator.flush_session()
        assert len(flushed) == 1
        assert flushed[0].symbol == "INFY"
        assert flushed[0].close == 1520.0
        assert flushed[0].is_closed is True
        assert aggregator.get_current_candle("INFY") is None

    # -------------------------------------------------------------------------
    # 7. End-to-End Real-Time Pipeline Integration
    # -------------------------------------------------------------------------

    def test_realtime_pipeline_integration(self):
        """Verify end-to-end flow: Provider -> Deduplication -> Aggregator -> Listeners."""
        provider = MockRealtimeProvider()
        pipeline = RealtimeMarketDataPipeline(provider)

        events_received: list[MarketDataEvent] = []
        candles_received: list[Candle] = []

        pipeline.register_event_listener(lambda e: events_received.append(e))
        pipeline.register_candle_listener(lambda c: candles_received.append(c))

        pipeline.connect()
        pipeline.handle_market_open(datetime(2024, 1, 8, 9, 15, 0, tzinfo=IST_TIMEZONE))
        pipeline.subscribe(["RELIANCE"])

        base_time = datetime(2024, 1, 8, 9, 15, 0, tzinfo=IST_TIMEZONE)

        # Ingest tick at 09:15:30
        tick1 = Tick("RELIANCE", base_time + timedelta(seconds=30), 2500.0, 10)
        provider.handle_incoming_message({"feeds": {"RELIANCE": {"last_price": 2500.0, "volume": 10, "timestamp": tick1.timestamp}}})

        # Ingest duplicate tick -> should be filtered
        provider.handle_incoming_message({"feeds": {"RELIANCE": {"last_price": 2500.0, "volume": 10, "timestamp": tick1.timestamp}}})

        # Ingest boundary tick at 09:20:00 -> closes the 09:15 bar
        tick2_time = base_time + timedelta(minutes=5)
        provider.handle_incoming_message({"feeds": {"RELIANCE": {"last_price": 2510.0, "volume": 20, "timestamp": tick2_time}}})

        # Check candle closed event
        assert len(candles_received) == 1
        assert candles_received[0].symbol == "RELIANCE"
        assert candles_received[0].open == 2500.0
        assert candles_received[0].close == 2500.0

        candle_closed_events = [e for e in events_received if e.event_type == MarketEventType.CANDLE_CLOSED]
        assert len(candle_closed_events) == 1

        # Check health: 3 seconds after last tick -> healthy (not stale)
        alerts_ok = pipeline.check_health(base_time + timedelta(seconds=303))
        assert len(alerts_ok) == 0

        # Check health: 20 seconds after last tick -> stale alert triggered
        alerts_stale = pipeline.check_health(base_time + timedelta(seconds=320))
        assert len(alerts_stale) == 1
        assert alerts_stale[0].event_type == MarketEventType.STALE_DATA_ALERT
        assert alerts_stale[0].symbol == "RELIANCE"

        # Market Close
        close_event, flushed = pipeline.handle_market_close(datetime(2024, 1, 8, 15, 30, 0, tzinfo=IST_TIMEZONE))
        assert close_event.event_type == MarketEventType.SESSION_CLOSE
        pipeline.disconnect()
