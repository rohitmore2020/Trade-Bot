# Strategy Parameters Specification: VWAP-ORB

This document defines all tunable and fixed parameters for the **VWAP Pullback with ORB Confirmation (VWAP-ORB)** intraday strategy.

---

## 1. Parameter Dictionary

| Parameter Name | Data Type | Default Value | Valid Range / Constraints | Unit | Description |
|---|---|---|---|---|---|
| `universe_fno_only` | `bool` | `True` | `[True, False]` | Boolean | Restrict universe strictly to NSE F&O eligible stocks |
| `min_turnover_cr` | `float` | `100.0` | `[10.0, 1000.0]` | ₹ Crores | Minimum average daily turnover required |
| `turnover_lookback_days` | `int` | `30` | `[10, 60]` | Days | Historical lookback for calculating average turnover |
| `min_atr_pct` | `float` | `1.5` | `[0.5, 5.0]` | Percentage (%) | Minimum 20-day ATR as a percentage of stock price |
| `max_atr_pct` | `float` | `6.0` | `[3.0, 15.0]` | Percentage (%) | Maximum 20-day ATR as a percentage of stock price |
| `atr_universe_period` | `int` | `20` | `[10, 50]` | Days | Daily ATR lookback period for universe volatility screening |
| `min_price` | `float` | `200.0` | `[10.0, 1000.0]` | ₹ (INR) | Minimum stock price for universe eligibility |
| `max_price` | `float` | `5000.0` | `[1000.0, 50000.0]`| ₹ (INR) | Maximum stock price for universe eligibility |
| `min_premarket_volume_pct` | `float` | `0.10` | `[0.01, 0.50]` | Fraction (0.10 = 10%) | Pre-market volume threshold relative to daily average volume |
| `min_gap_pct` | `float` | `0.01` | `[0.005, 0.05]` | Fraction (0.01 = 1%) | Minimum overnight gap threshold |
| `orb_start_time` | `time` | `09:15:00` | Fixed NSE open | IST Time | Start of the Opening Range window |
| `orb_end_time` | `time` | `09:30:00` | `09:20:00` to `10:00:00` | IST Time | End of the Opening Range window (15 min duration) |
| `trading_window_start` | `time` | `09:45:00` | `09:30:00` to `11:00:00` | IST Time | Earliest permitted entry time for strategy signals |
| `trading_window_end` | `time` | `14:30:00` | `13:30:00` to `15:15:00` | IST Time | Latest permitted entry time and mandatory exit time |
| `candle_timeframe_seconds` | `int` | `300` | `[60, 900]` | Seconds (300 = 5m) | Execution timeframe for signal generation candle bars |
| `pullback_threshold_long` | `float` | `1.002` | `[1.000, 1.010]` | Multiplier | Price multiplier on VWAP for Long pullback (`low <= vwap * 1.002`) |
| `pullback_threshold_short` | `float` | `0.998` | `[0.990, 1.000]` | Multiplier | Price multiplier on VWAP for Short pullback (`high >= vwap * 0.998`) |
| `volume_surge_multiplier` | `float` | `1.5` | `[1.1, 3.0]` | Multiplier | Multiplier over 10-bar SMA volume (`vol >= 1.5 * sma_vol`) |
| `volume_sma_period` | `int` | `10` | `[5, 30]` | Bars | Lookback period for volume moving average |
| `limit_order_offset_pct` | `float` | `0.0005` | `[0.0001, 0.0020]` | Fraction (0.05%) | Offset added to Close for limit entry (`close * (1 + offset)`) |
| `atr_period` | `int` | `14` | `[5, 30]` | Bars | Bar lookback for intraday ATR calculation |
| `stop_loss_atr_mult` | `float` | `1.5` | `[1.0, 3.0]` | Multiplier | ATR multiplier for initial Stop Loss (`entry - 1.5 * ATR`) |
| `trailing_stop_atr_mult` | `float` | `2.0` | `[1.0, 4.0]` | Multiplier | ATR multiplier for dynamic trailing stop (`peak - 2.0 * ATR`) |
| `vwap_exit_enabled` | `bool` | `True` | `[True, False]` | Boolean | Enable emergency exit when price crosses VWAP against position |
| `risk_per_trade_pct` | `float` | `0.005` | `[0.001, 0.020]` | Fraction (0.5% of equity) | Fractional risk allocated per trade |
| `max_capital_per_trade_pct`| `float` | `0.20` | `[0.05, 0.50]` | Fraction (20% of equity) | Maximum notional capital allowed in a single position |
| `max_open_positions` | `int` | `3` | `[1, 10]` | Count | Maximum simultaneous active positions permitted |
| `max_daily_trades` | `int` | `6` | `[1, 20]` | Count | Maximum total fills allowed in a single trading day |
| `max_daily_loss_pct` | `float` | `0.02` | `[0.005, 0.05]` | Fraction (2% of equity) | Maximum cumulative daily loss before circuit breaker trips |

---

## 2. Configuration Schema Mapping (YAML / Environment)

```yaml
strategy:
  name: "VWAP_ORB"
  timeframe_seconds: 300 # 5 minutes
  
  universe:
    fno_only: true
    min_turnover_cr: 100.0
    turnover_lookback_days: 30
    min_atr_pct: 1.5
    max_atr_pct: 6.0
    atr_universe_period: 20
    min_price: 200.0
    max_price: 5000.0
    min_premarket_volume_pct: 0.10
    min_gap_pct: 0.01

  timings:
    orb_start: "09:15:00"
    orb_end: "09:30:00"
    window_start: "09:45:00"
    window_end: "14:30:00"

  rules:
    pullback_tolerance_long: 1.002
    pullback_tolerance_short: 0.998
    volume_surge_multiplier: 1.5
    volume_sma_period: 10
    limit_offset_pct: 0.0005
    atr_period: 14
    initial_sl_atr_mult: 1.5
    trailing_sl_atr_mult: 2.0
    vwap_exit_enabled: true

  risk:
    risk_per_trade_pct: 0.005 # 0.5%
    max_capital_per_trade_pct: 0.20 # 20%
    max_open_positions: 3
    max_daily_trades: 6
    max_daily_loss_pct: 0.02 # 2%
```
