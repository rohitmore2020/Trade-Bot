# Research Conclusions & Architecture Recommendations: Phase 2

## 1. Executive Summary
Phase 2 rigorously investigated the quantitative foundation, market microstructure, and regulatory environment governing the **VWAP-ORB** trading strategy for Indian NSE cash equities.

The core premise of the strategy—combining **market regime filtering**, **Opening Range reference levels**, **VWAP pullback value anchoring**, **volume surge confirmation**, and **volatility-adjusted ATR stops**—is structurally sound and addresses major weaknesses found in naive breakout strategies.

However, the research identified **four direct conflicts with exchange and broker realities** and highlighted significant **frictional drag** (6 to 10 bps per round trip) that will erode profitability unless accurately modeled.

---

## 2. Synthesis Matrix: Facts vs. Strategy Assumptions

| Area | Verified Market / Academic Fact | Strategy Assumption | Assessment / Action |
|---|---|---|---|
| **Stop Loss Order Type** | NSE and brokers heavily restrict or disallow `SL-M` (Stop Loss Market) to prevent freak trades. | Strategy specifies `SL-M` order for the initial stop-loss. | **CONFLICT**: Must substitute with `SL-L` (Stop-Loss Limit) order with a defined trigger-to-limit buffer. |
| **Benchmark VWAP** | NIFTY 50 Spot Index has no traded volume; true VWAP cannot be calculated on spot data. | Strategy assumes `NIFTY > VWAP -> Long; NIFTY < VWAP -> Short`. | **CONFLICT**: Benchmark VWAP must be computed on **NIFTY Front-Month Futures** or use Spot TWAP. |
| **F&O Universe Survivorship** | NSE updates F&O list dynamically; using today's list across 2023–2024 introduces severe survivorship bias. | Strategy assumes a static or unanchored dynamic F&O universe. | **BACKTEST RISK**: Must maintain a point-in-time historical constituent database. |
| **Transaction Frictions** | SEBI 2024 report proves 71% of intraday traders lose money, with costs adding 57% to net losses. | Strategy expects net Profit Factor 1.2–1.5 with realistic costs. | **VALIDATED**: The 6-trade/day cap and 0.5% risk limit are essential to surviving cost drag. |
| **Intra-Bar Granularity** | 5-minute OHLC bars cannot resolve whether Low touched VWAP before High broke ORB level. | Strategy evaluates 5-minute candle logic. | **SIMULATION REQUIREMENT**: Backtester must evaluate 5m logic using underlying 1-minute or tick series. |
| **Pre-Market Volume** | Pre-market call auction volume $\ge 10\%$ of daily average is an extreme outlier (<1% of trading days). | Strategy filters universe by `Pre-market volume >= 10% OR gap >= 1%`. | **OPERATIONAL RISK**: Gap filter ($\ge 1\%$) will trigger almost all candidates; volume filter will rarely trigger. |

---

## 3. Direct Conflicts Identified (Requires User Review)

> [!IMPORTANT]
> ### 1. The SL-M Order Conflict
> - **Strategy Document**: *"Stop Loss: 1.5× ATR(14) below entry (SL-M order)"*
> - **Regulatory / Broker Reality**: Exchange circulars and Upstox API directives reject or restrict SL-M orders on volatile cash equities to prevent freak executions.
> - **Proposed Resolution**: Use a **Stop-Loss Limit (`SL-L`)** order with:
>   - Trigger Price = $\text{Entry} - (1.5 \times \text{ATR})$
>   - Limit Price = $\text{Trigger Price} - (0.5 \times \text{ATR})$ (or 0.5% buffer) to ensure fill during sharp drops while preventing catastrophic freak trade fills.
>
> ### 2. NIFTY VWAP Calculation Method
> - **Strategy Document**: *"Regime: NIFTY > VWAP → LONG only; NIFTY < VWAP → SHORT only"*
> - **Exchange Reality**: The headline NIFTY 50 index (NSE: `NIFTY 50`) is a market-cap weighted index value without native volume ticks.
> - **Proposed Resolution**: Specify whether the regime filter evaluates:
>   - Option A: **NIFTY Front-Month Futures** contract (has real exchange volume and exact VWAP).
>   - Option B: NIFTY 50 Spot Index using **Time-Weighted Average Price (TWAP)** or 20-period Moving Average as proxy.
>
> ### 3. Fixed 0.2% Pullback Tolerance vs Stock Volatility
> - **Strategy Document**: *"Pullback: low ≤ VWAP × 1.002"*
> - **Empirical Reality**: A fixed 0.2% tolerance is rigid. For a stock with daily ATR of 5% (e.g. ₹150 on a ₹3,000 stock), a 5-minute candle can swing 0.4% without violating trend integrity.
> - **Preservation Note**: Per engineering rules, we did **not** modify this parameter. It is noted for review during empirical backtest validation.
>
> ### 4. Trailing Stop Frequency vs Broker API Rate Limits
> - **Strategy Document**: *"Trail with 2× ATR"*
> - **API Reality**: Upstox enforces rate limits of 10 requests per second. Modifying stop orders on every tick across 3 active positions will trigger HTTP 429 rate limit exceptions.
> - **Proposed Resolution**: Update trailing stop orders on **5-minute bar closes** or when price advances by at least $0.5 \times \text{ATR}$.

---

## 4. Backtest Engine Architecture Recommendations (For Phase 3)

To ensure the Phase 3 backtester produces institutional-grade, verifiable results:

1. **Dual-Timeframe Architecture**:
   - Ingest **1-minute data** to construct **5-minute strategy bars**.
   - Evaluate signals on 5-minute close, but execute fills and track stop-loss/trailing exits on 1-minute bars to eliminate intra-bar look-ahead bias and OHLC sequence ambiguity.
2. **Realistic Fill Modeling**:
   - For LIMIT BUY at `Close + 0.05%`: Require market to trade at or below limit price in the next bar.
   - Model slippage of at least 1 tick (0.02% to 0.05%) on market/SL exits.
3. **Point-in-Time F&O Universe Tracking**:
   - Filter universe dynamically on each trading day without look-ahead knowledge of future stock inclusion/exclusion.
4. **Comprehensive Indian Cost Engine**:
   - Deduct full statutory fees: Brokerage (₹20), STT (0.025% on sell), NSE charges (0.00345%), SEBI charges (₹10/Cr), Stamp duty (0.003% on buy), and 18% GST.

---

## 5. Scope Control Confirmation
- No strategy rules were modified.
- No parameters were altered or optimized.
- Live trading infrastructure remains strictly locked.
- Ready to proceed to **Phase 3 (Backtester Implementation & Validation)** upon user review and approval.
