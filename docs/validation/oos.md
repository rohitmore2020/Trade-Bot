# Out-of-Sample Validation: VWAP-ORB

## Purpose
Determines whether strategy edge persists on unseen market data or collapses due to curve-fitting.

## Configuration & Parameters
- **Strategy Version**: VWAP_ORB_V1.0
- **Parameters**: `pullback_threshold`: 1.002, `volume_surge`: 1.5, `initial_sl_atr`: 1.5, `trailing_sl_atr`: 2.0

## Comparison Matrix
| Metric | In-Sample (IS) | Out-of-Sample (OOS) | Degradation / Delta |
| :--- | :--- | :--- | :--- |
| **Dataset Period** | 2023-01-01 to 2023-12-31 (12 Months) | 2024-01-01 to 2024-06-30 (6 Months) | - |
| **Total Trades** | 140 | 80 | - |
| **Win Rate** | 55.7% | 51.2% | -4.5% |
| **Profit Factor** | 2.75 | 1.80 | 65.5% of IS |
| **Net P&L** | ₹38,198.14 | ₹10,715.07 | - |
| **Expectancy** | ₹272.84 / trade | ₹133.94 / trade | -138.90 / trade |
| **Max Drawdown** | 4.85% | 6.15% | +1.30% |
| **Sharpe Ratio** | 1.78 | 1.42 | -0.36 |
| **Max Losing Streak** | 4 trades | 5 trades | +1 trades |

## OOS Verdict
- **Target Threshold**: OOS Profit Factor $\ge 1.20$
- **Actual OOS PF**: 1.80 (PASSED)
