# Parameter Sensitivity Analysis: VWAP-ORB

## Methodology
Evaluates whether small perturbations to strategy parameters cause abrupt cliff-drops in profitability.
Only the approved restricted parameter ranges from the strategy specification are tested.

- **Dataset Period**: 2023-01-01 to 2024-06-30 (Full Evaluation Period)
- **Strategy Version**: VWAP_ORB_V1.0

### Parameter: `pullback_threshold_long` (Default: `1.002`)
- **Stability Status**: **STABLE**
- **Profit Factor CV**: 0.0423
- **Cliff Warning**: None detected

| Value | Trades | Win Rate | Profit Factor | Expectancy | Max DD | Sharpe | Losing Streak | Net P&L | Sensitivity vs Default |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1.0 | 180 | 54.0% | 2.53 | ₹170.00 | 5.80% | 1.45 | 5 | ₹30,600.00 | -8.0% |
| 1.002 | 220 | 57.0% | 2.75 | ₹210.00 | 5.20% | 1.65 | 4 | ₹46,200.00 | +0.0% |
| 1.005 | 250 | 56.0% | 2.61 | ₹195.00 | 5.50% | 1.55 | 4 | ₹48,750.00 | -5.1% |

### Parameter: `volume_surge_multiplier` (Default: `1.5`)
- **Stability Status**: **STABLE**
- **Profit Factor CV**: 0.0898
- **Cliff Warning**: None detected

| Value | Trades | Win Rate | Profit Factor | Expectancy | Max DD | Sharpe | Losing Streak | Net P&L | Sensitivity vs Default |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1.2 | 280 | 53.0% | 2.42 | ₹160.00 | 6.20% | 1.38 | 6 | ₹44,800.00 | -12.0% |
| 1.5 | 220 | 57.0% | 2.75 | ₹210.00 | 5.20% | 1.65 | 4 | ₹46,200.00 | +0.0% |
| 1.8 | 160 | 60.0% | 2.89 | ₹240.00 | 4.80% | 1.72 | 4 | ₹38,400.00 | +5.1% |

### Parameter: `initial_sl_atr_mult` (Default: `1.5`)
- **Stability Status**: **STABLE**
- **Profit Factor CV**: 0.0580
- **Cliff Warning**: None detected

| Value | Trades | Win Rate | Profit Factor | Expectancy | Max DD | Sharpe | Losing Streak | Net P&L | Sensitivity vs Default |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1.2 | 220 | 52.0% | 2.45 | ₹165.00 | 6.50% | 1.40 | 5 | ₹36,300.00 | -10.9% |
| 1.5 | 220 | 57.0% | 2.75 | ₹210.00 | 5.20% | 1.65 | 4 | ₹46,200.00 | +0.0% |
| 2.0 | 220 | 59.0% | 2.58 | ₹190.00 | 5.70% | 1.52 | 4 | ₹41,800.00 | -6.2% |

### Parameter: `trailing_sl_atr_mult` (Default: `2.0`)
- **Stability Status**: **STABLE**
- **Profit Factor CV**: 0.0476
- **Cliff Warning**: None detected

| Value | Trades | Win Rate | Profit Factor | Expectancy | Max DD | Sharpe | Losing Streak | Net P&L | Sensitivity vs Default |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1.5 | 220 | 58.0% | 2.50 | ₹175.00 | 5.90% | 1.48 | 4 | ₹38,500.00 | -9.1% |
| 2.0 | 220 | 57.0% | 2.75 | ₹210.00 | 5.20% | 1.65 | 4 | ₹46,200.00 | +0.0% |
| 2.5 | 220 | 55.0% | 2.64 | ₹200.00 | 5.40% | 1.58 | 5 | ₹44,000.00 | -4.0% |
