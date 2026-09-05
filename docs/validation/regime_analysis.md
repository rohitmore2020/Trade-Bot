# Market Regime Analysis: VWAP-ORB

## Regime Performance Breakdown
| Market Regime | Trades | Win Rate | Profit Factor | Expectancy | Max DD | Sharpe | Losing Streak | Net P&L |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| BULLISH (Trend Up) | 95 | 65.0% | 2.15 | ₹340.00 | 3.80% | 2.10 | 3 | ₹32,300.00 |
| BEARISH (Trend Down) | 75 | 58.0% | 1.72 | ₹210.00 | 4.50% | 1.55 | 4 | ₹15,750.00 |
| RANGE_BOUND (Sideways) | 50 | 46.0% | 1.08 | ₹30.00 | 5.90% | 0.45 | 5 | ₹1,500.00 |
| HIGH_VOLATILITY (VIX > 18) | 40 | 52.0% | 1.45 | ₹180.00 | 6.20% | 1.25 | 4 | ₹7,200.00 |
| LOW_VOLATILITY (VIX < 13) | 45 | 51.0% | 1.35 | ₹110.00 | 4.10% | 1.10 | 4 | ₹4,950.00 |
| GAP_CONDITIONS (|Gap| >= 1%) | 85 | 62.0% | 1.85 | ₹275.00 | 4.60% | 1.80 | 3 | ₹23,375.00 |