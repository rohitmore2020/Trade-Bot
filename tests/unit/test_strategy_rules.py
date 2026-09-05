"""
Unit tests for VWAP-ORB Deterministic Strategy Rules.
"""

from datetime import datetime, time, timezone
from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import Candle
from trade_bot.indicators.orb import ORBLevels
from trade_bot.strategy.models import (
    MarketRegime,
    SignalTriggerReason,
    UniverseCandidate,
    VwapOrbStrategyConfig,
)
from trade_bot.strategy.rules import (
    MarketRegimeRule,
    PositionSizer,
    SessionRiskGuard,
    StopLossRule,
    TimeExitRule,
    TrailingStopRule,
    VwapExitRule,
    VwapOrbSignalRule,
)


def test_universe_candidate_eligibility() -> None:
    # Qualifying candidate
    cand = UniverseCandidate(
        symbol="RELIANCE",
        price=2500.0,
        avg_daily_turnover_cr=150.0,
        atr_20d_pct=2.5,
        premarket_volume_pct=0.12,
        overnight_gap_pct=0.005,
        is_fno_eligible=True,
    )
    assert cand.is_eligible is True

    # Fails turnover (< 100 Cr)
    assert UniverseCandidate(
        symbol="LOW_TO",
        price=2500.0,
        avg_daily_turnover_cr=80.0,
        atr_20d_pct=2.5,
        premarket_volume_pct=0.12,
        overnight_gap_pct=0.005,
    ).is_eligible is False

    # Fails ATR (> 6%)
    assert UniverseCandidate(
        symbol="HIGH_VOL",
        price=2500.0,
        avg_daily_turnover_cr=150.0,
        atr_20d_pct=7.0,
        premarket_volume_pct=0.12,
        overnight_gap_pct=0.005,
    ).is_eligible is False

    # Fails Price (< 200)
    assert UniverseCandidate(
        symbol="PENNY",
        price=150.0,
        avg_daily_turnover_cr=150.0,
        atr_20d_pct=2.5,
        premarket_volume_pct=0.12,
        overnight_gap_pct=0.005,
    ).is_eligible is False


def test_market_regime_rule() -> None:
    assert MarketRegimeRule.evaluate(22100.0, 22000.0) == MarketRegime.BULLISH
    assert MarketRegimeRule.evaluate(21900.0, 22000.0) == MarketRegime.BEARISH
    assert MarketRegimeRule.evaluate(22000.0, 22000.0) == MarketRegime.NEUTRAL


def test_vwap_orb_long_signal_evaluation() -> None:
    rule = VwapOrbSignalRule()
    orb = ORBLevels(
        high=2500.0,
        low=2450.0,
        range=50.0,
        is_complete=True,
        calculated_at=datetime(2026, 9, 5, 9, 30, tzinfo=timezone.utc),
    )

    # Valid Long Candidate:
    # Time: 10:00 IST (in 09:45-14:30)
    # Regime: Bullish
    # Stock VWAP: 2510
    # Candle: Open=2515, High=2535, Low=2512 (within 2510 * 1.002 = 2515.02), Close=2530 (> Open, > VWAP, > OR High of 2500)
    # Volume: 20000 (>= 1.5 * 10000)
    c = Candle(
        symbol="RELIANCE",
        timestamp=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
        open=2515.0,
        high=2535.0,
        low=2512.0,
        close=2530.0,
        volume=20000,
        timeframe_seconds=300,
    )

    result = rule.evaluate_long(
        candle=c,
        stock_vwap=2510.0,
        orb_levels=orb,
        volume_sma_10=10000.0,
        regime=MarketRegime.BULLISH,
        atr_14=20.0,
    )
    assert result.is_signal is True
    assert result.trigger_reason == SignalTriggerReason.LONG_ENTRY
    # Limit entry = Close * 1.0005 = 2530 * 1.0005 = 2531.265 -> 2531.26
    assert result.limit_entry_price == 2531.26
    # Initial SL = 2531.26 - (1.5 * 20.0) = 2501.26
    assert result.initial_stop_price == 2501.26


def test_vwap_orb_long_signal_rejections() -> None:
    rule = VwapOrbSignalRule()
    orb = ORBLevels(
        high=2500.0,
        low=2450.0,
        range=50.0,
        is_complete=True,
        calculated_at=datetime.now(timezone.utc),
    )

    # Outside window (09:35 IST < 09:45 IST)
    c_early = Candle(
        symbol="RELIANCE",
        timestamp=datetime(2026, 9, 5, 9, 35, tzinfo=timezone.utc),
        open=2515.0,
        high=2535.0,
        low=2512.0,
        close=2530.0,
        volume=20000,
    )
    res_early = rule.evaluate_long(c_early, 2510.0, orb, 10000.0, MarketRegime.BULLISH, 20.0)
    assert res_early.is_signal is False
    assert res_early.trigger_reason == SignalTriggerReason.OUTSIDE_TRADING_WINDOW

    # Regime mismatch (Bearish)
    c_valid = Candle(
        symbol="RELIANCE",
        timestamp=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
        open=2515.0,
        high=2535.0,
        low=2512.0,
        close=2530.0,
        volume=20000,
    )
    res_regime = rule.evaluate_long(c_valid, 2510.0, orb, 10000.0, MarketRegime.BEARISH, 20.0)
    assert res_regime.is_signal is False
    assert res_regime.trigger_reason == SignalTriggerReason.REGIME_MISMATCH

    # No pullback (Low = 2520, which is > 2510 * 1.002 = 2515.02)
    c_no_pullback = Candle(
        symbol="RELIANCE",
        timestamp=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
        open=2522.0,
        high=2535.0,
        low=2520.0,
        close=2530.0,
        volume=20000,
    )
    res_pb = rule.evaluate_long(c_no_pullback, 2510.0, orb, 10000.0, MarketRegime.BULLISH, 20.0)
    assert res_pb.is_signal is False
    assert res_pb.trigger_reason == SignalTriggerReason.NO_PULLBACK


def test_trailing_stop_rule_ratchets_properly() -> None:
    # Long: initial stop 2500, atr = 20 (2 * 20 = 40 trail distance)
    # Price rises to 2560 -> trail level = 2560 - 40 = 2520 (ratchets up)
    stop1 = TrailingStopRule.update_long(current_stop=2500.0, highest_price_since_entry=2560.0, atr=20.0)
    assert stop1 == 2520.0

    # Price drops to 2540 -> highest price remains 2560, stop does NOT move down
    stop2 = TrailingStopRule.update_long(current_stop=stop1, highest_price_since_entry=2560.0, atr=20.0)
    assert stop2 == 2520.0


def test_position_sizer_exact_fractional_risk() -> None:
    # Capital = 1,000,000. Risk = 0.5% = 5,000.
    # Entry = 2500, SL = 2450 (Risk = 50/share).
    # Qty = 5000 / 50 = 100 shares.
    # Capital cap = 20% of 1,000,000 = 200,000 / 2500 = 80 shares.
    # Capped qty should be 80.
    res = PositionSizer.calculate(
        equity=1000000.0,
        entry_price=2500.0,
        stop_price=2450.0,
        risk_pct=0.005,
        max_capital_pct=0.20,
    )
    assert res.quantity == 80
    assert res.is_capital_capped is True
    assert res.notional_value == 200000.0


def test_session_risk_guard() -> None:
    # Allowed
    ok, msg = SessionRiskGuard.can_open_position(1, 2, 0.005)
    assert ok is True
    assert msg is None

    # Exceeds max open positions (3)
    ok_pos, msg_pos = SessionRiskGuard.can_open_position(3, 2, 0.005)
    assert ok_pos is False
    assert "Maximum open positions" in msg_pos

    # Exceeds max daily trades (6)
    ok_trd, msg_trd = SessionRiskGuard.can_open_position(1, 6, 0.005)
    assert ok_trd is False
    assert "Maximum daily trades" in msg_trd

    # Exceeds daily loss cap (2%)
    ok_loss, msg_loss = SessionRiskGuard.can_open_position(1, 2, 0.021)
    assert ok_loss is False
    assert "Daily loss cap" in msg_loss


def test_exits_vwap_and_time() -> None:
    # Long VWAP exit: price < vwap
    assert VwapExitRule.should_exit_long(2495.0, 2500.0) is True
    assert VwapExitRule.should_exit_long(2505.0, 2500.0) is False

    # Short VWAP exit: price > vwap
    assert VwapExitRule.should_exit_short(2505.0, 2500.0) is True

    # Time exit: >= 14:30
    assert TimeExitRule.should_exit(time(14, 30, 0)) is True
    assert TimeExitRule.should_exit(time(14, 35, 0)) is True
    assert TimeExitRule.should_exit(time(14, 25, 0)) is False
