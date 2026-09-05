# Monte Carlo Simulation Report: VWAP-ORB

## Simulation Setup
- **Iterations**: 2,000 bootstrap permutations
- **Initial Capital**: ₹100,000.00

## Terminal Equity Percentiles
| Percentile | Terminal Equity | Implied Return |
| :--- | :--- | :--- |
| **99th Percentile (Optimistic Tail)** | ₹171,544.25 | +71.5% |
| **75th Percentile** | ₹155,475.78 | +55.5% |
| **50th Percentile (Median)** | ₹148,711.21 | +48.7% |
| **25th Percentile** | ₹142,045.39 | +42.0% |
| **5th Percentile (Adverse Tail)** | ₹132,827.19 | +32.8% |

## Sequence Risk & Tail Metrics
- **Median Max Drawdown**: 2.99%
- **95th Percentile Max Drawdown**: 5.03%
- **Worst-Case Simulation Drawdown**: 9.55%
- **Median Losing Streak**: 6 consecutive trades
- **95th Percentile Losing Streak**: 9 consecutive trades
- **Probability of Net Loss**: 0.0%
- **Risk of Ruin (> 20% DD)**: 0.00%
