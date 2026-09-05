# Backtesting Methodology & Simulation Hazards: Indian NSE Equities

## 1. Overview
A backtest is a simulation model of reality. Because financial markets are non-stationary, complex adaptive systems, backtests that fail to rigorously account for simulation biases, data survivorship, intra-bar sequence uncertainty, and look-ahead artifacts produce wildly inflated performance metrics that collapse upon live deployment.

This document identifies the specific quantitative backtesting risks and methodological pitfalls relevant to the **VWAP-ORB** strategy.

---

## 2. Facts Supported by Sources

### 2.1 Survivorship Bias in NSE F&O Universe
- **Dynamic F&O Eligibility**:
  - SEBI mandates rigorous eligibility and exclusion criteria for derivatives trading on NSE (e.g. Market Wide Position Limit $\ge ₹1,500\text{ crore}$, median quarter sigma order size $\ge ₹75\text{ lakh}$, average daily turnover in cash market).
  - Every month, NSE issues circulars adding newly eligible companies and **excluding** companies that fail liquidity or market-cap thresholds.
  - Examples: Historically prominent stocks (e.g., DHFL, YES Bank, Reliance Communications, PC Jeweller, Zee Entertainment) were active in F&O before suffering 80%–99% declines and subsequently being removed from the F&O segment.
- **The Bias**:
  - If a backtest conducted over 2023–2026 uses the **current (2026) F&O stock list**, it tests exclusively on companies that survived and prospered up to 2026. This creates a severe upward performance distortion (survivorship bias), as past losers are systematically omitted.
  - Source: *SEBI Master Circular on Eligibility Criteria of Stocks in Derivatives Segment; Brown et al. (1992, "Survivorship Bias in Performance Studies")*.

### 2.2 Look-Ahead Bias & Bar-Boundary Execution
- **Candle Close Fallacy**:
  - A 5-minute candle spanning 10:00:00 to 10:05:00 IST is not finalized until the clock strikes **10:05:00.000**.
  - Any backtest simulation that assumes an order is executed at the `Close` price of the 10:00–10:05 bar possesses look-ahead bias: the close price is only known *retrospectively* after the bar is finished.
  - An order triggered by the close of bar $t$ can only be transmitted and matched at the `Open` (or during the price progression) of bar $t+1$.

### 2.3 Intra-Bar Sequence Uncertainty (OHLC Inversion Trap)
- In a standard OHLC bar, the sequence of prices between `Open` and `Close` is unknown:
  - Did the price go $\text{Open} \to \text{Low} \to \text{High} \to \text{Close}$?
  - Or did it go $\text{Open} \to \text{High} \to \text{Low} \to \text{Close}$?
- For the VWAP-ORB strategy, which evaluates:
  1. Pullback: $\text{Low} \le \text{VWAP} \times 1.002$
  2. Breakout: $\text{Close} > \text{OR}_{\text{high}}$
  3. Stop Loss: $\text{Price} \le \text{Entry} - 1.5 \times \text{ATR}$
- If both the entry condition and stop-loss level are touched during the same 5-minute bar, an OHLC backtester cannot determine whether the trade was stopped out before reaching the high, or reached the target first.

---

## 3. Research Findings

### 3.1 Parameter Overfitting & The Multiple Testing Curse
- **Harvey, Liu, and Zhu (2016, *...and the Cross-Section of Expected Returns*, Journal of Finance)**:
  - Testing multiple parameter combinations on the same historical dataset dramatically inflates the probability of discovering false discoveries (spurious alpha).
  - The VWAP-ORB strategy contains **at least 12 degrees of freedom**:
    - Universe filters (Turnover ₹100 Cr, ATR 1.5%–6%, Price ₹200–₹5000, Premarket 10%, Gap 1%)
    - Time window (09:45–14:30)
    - Pullback tolerance (0.2%)
    - Volume surge multiplier (1.5x)
    - Volume SMA lookback (10 bars)
    - ATR period (14)
    - Initial stop-loss multiplier (1.5x)
    - Trailing stop multiplier (2.0x)
- **Finding**: With 12 parameters, it is trivial to find a combination that yields a backtest Profit Factor $> 1.8$ on 2023–2024 data through data mining. Without strict **Walk-Forward Analysis (WFA)** and **Monte Carlo Permutation Tests**, such backtests are statistically invalid.

### 3.2 Limit Order Fill Modeling in Historical Data
- Traditional backtesters assume that if `Candle.Low <= Limit Price`, a Limit Buy order is 100% filled at the limit price.
- In reality, thousands of limit orders may sit in the queue ahead of our order. If price merely touches the limit price without trading through it, the order is rarely filled.
- **Finding**: A realistic backtest must enforce a "trade-through" condition: a Limit Buy order at price $P$ is only modeled as filled if the market trades strictly below $P$ (e.g., $\text{Low} < P$), or models volume-dependent fill probabilities.

---

## 4. Assumptions in Our Strategy

1. **Survivorship-Free F&O Universe**:
   - Assumes point-in-time historical constituents of the NSE F&O segment can be retrieved for backtesting 2023–2024.
2. **Deterministic Intra-Bar Fills**:
   - Assumes that because limit orders are placed at `Close + 0.05%` (slightly aggressive limit), they execute immediately on the opening tick of the next bar.
3. **Tick-Accurate Stop-Loss Triggering**:
   - Assumes stop-loss orders are evaluated continuously at tick level rather than solely at bar close.
4. **Independent Asset Behavior**:
   - Assumes signals across different stocks in the universe are independent, even though simultaneous signals in banking stocks (e.g. HDFCBANK, ICICIBANK, SBIN, KOTAKBANK) are highly collinear and multiply market beta risk.

---

## 5. Unresolved Questions & Conflicts

> [!WARNING]
> ### Critical Conflict: Historical F&O Membership Data Availability
> - The strategy specifies: "Stocks: Dynamic universe of 10–30 F&O-eligible NSE stocks daily".
> - Standard low-cost data feeds (Yahoo Finance, basic Upstox historical candles) provide data for *currently active* symbols only. They do **not** provide historical point-in-time F&O constituent lists.
> - **Action Required**: The backtest architecture must maintain an explicit historical registry of F&O inclusions and exclusions for each month from 2023 to 2026 to prevent survivorship bias from inflating the results.
>
> ### Intra-Bar Execution Priority
> - When running backtests on 5-minute OHLCV candles, how does the engine resolve intra-bar conflicts when a bar's High breaches the trailing stop ratchet level while its Low breaches the initial stop-loss level?
> - **Resolution Needed**: Must the backtesting engine ingest 1-minute bars (or tick data) to evaluate 5-minute strategy signals, ensuring unambiguous chronological execution?
