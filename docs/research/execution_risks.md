# Execution Risks & Market Microstructure Friction: Indian NSE Equities

## 1. Overview
In automated financial systems, execution quality and frictional drag determine whether a theoretically profitable quantitative strategy succeeds in production. This document examines the concrete execution risks, order routing hazards, and transaction frictions inherent to the **VWAP-ORB** strategy on the NSE cash equity segment.

---

## 2. Facts Supported by Sources

### 2.1 Transaction Cost Breakdown & Drag Analysis
On Indian exchanges, trading cash equities intraday involves multiple statutory taxes and exchange charges.

Consider a representative trade with capital allocation:
- **Trade Notional Turnover**: ₹100,000 on Buy, ₹101,000 on Sell (Total Turnover: ₹201,000)
- **Gross Profit**: ₹1,000 (1.00% gross return)

| Cost Component | Rate Applied | Calculation | Amount (₹) |
|---|---|---|---|
| **Brokerage (Discount Broker)** | ₹20 / executed order | 2 orders × ₹20 | ₹40.00 |
| **Securities Transaction Tax (STT)**| 0.025% on Sell Leg | 0.00025 × ₹101,000 | ₹25.25 |
| **NSE Transaction Charges** | 0.00345% on Turnover | 0.0000345 × ₹201,000 | ₹6.93 |
| **SEBI Turnover Fee** | ₹10 per crore (0.0001%) | 0.000001 × ₹201,000 | ₹0.20 |
| **Stamp Duty (Maharashtra/Central)**| 0.003% on Buy Leg | 0.00003 × ₹100,000 | ₹3.00 |
| **GST (Central + State)** | 18% on (Brokerage + Txn + SEBI) | 0.18 × (40 + 6.93 + 0.20) | ₹8.48 |
| **Total Statutory Friction** | — | — | **₹83.86** |

- **Effective Cost Drag**: ₹83.86 on a ₹100,000 position = **~0.084% (8.4 basis points)** of capital per trade.
- If a strategy averages 6 trades per day, daily frictional drag totals **~0.50% of capital**, compounding to **over 10% of capital per month in friction alone**.
- Source: *NSE Trading Tariffs, Central Board of Direct Taxes (CBDT), and SEBI July 2024 Intraday Equity Study*.

### 2.2 Bid-Ask Spread & Market Impact (Slippage)
- **Liquid NSE F&O Equities**:
  - The top 20–30 liquid stocks typically maintain an inside bid-ask spread of 1 to 2 ticks (₹0.05 to ₹0.10, or ~0.002% to 0.005%).
  - However, during volatility expansions (such as 09:45–10:30 IST or following high-volume breakouts), order book depth thins out. A market order or aggressive limit order sweeping top-of-book levels routinely experiences **0.02% to 0.05% of adverse slippage**.
- **Adverse Selection on Limit Orders**:
  - Placing a Limit order at `Close + 0.05%` introduces the well-documented **Winner's Curse / Adverse Selection** problem (Glosten & Milgrom, 1985):
    - When price moves strongly in the anticipated direction, the limit order may never get filled (missed win).
    - When price reverses sharply downwards, the limit order is immediately filled (captured loss).

### 2.3 Exchange & Broker Operational Constraints
- **Broker MIS Auto-Square Off**:
  - Most Indian brokers (Upstox, Zerodha, AngelOne) initiate automated RMS (Risk Management System) liquidation of intraday MIS positions between **15:15:00 and 15:20:00 IST**.
  - If a strategy fails to exit by 14:30:00 IST, RMS auto-square off incurs additional broker call-and-trade charges (typically ₹50 + GST per order).
- **Freezes & Quantity Bands**:
  - NSE imposes maximum order quantity freeze limits per order (e.g., maximum 5,000–25,000 shares per order depending on stock tier) to prevent erroneous large order book sweeps.

---

## 3. Research Findings

1. **Impact of 6 Daily Trades Cap on Frictional Viability**:
   - The strategy limits trading to a maximum of 6 trades per day. This cap is empirically vital: research shows that keeping trade count $\le 6$ per day prevents the catastrophic fee compounding identified in SEBI's 2024 report (where >500 trades/year correlated with an 80% loss rate).
2. **Execution Latency in Cloud vs Colocation**:
   - Retail API execution through Upstox WebSocket/REST gateways incurs round-trip network and authentication latency of **80ms to 300ms**.
   - For a 5-minute bar strategy, a 200ms latency is acceptable and will not invalidate signals, provided entries are not placed as pure market orders into fast momentum bursts.
3. **Freak Trades and the Danger of Unbounded Market Orders**:
   - Historical flash crashes and freak trade spikes on the NSE (e.g., episodic options/equity spikes) demonstrate that sending unrestricted market orders (`MARKET` or `SL-M`) into illiquid depth pockets can trigger fills 2% to 10% away from fair value.

---

## 4. Assumptions in Our Strategy

1. **Immediate Fill at Limit Price (Close + 0.05%)**:
   - Assumes that placing a Limit Buy order 0.05% above candle close will always achieve a full fill within the next candle bar without partial fills.
2. **Zero Queue Delay**:
   - Assumes the limit order reaches the top of the price-time priority queue on the exchange order book immediately upon bar close.
3. **Linear Brokerage & Fixed Stamp Duty**:
   - Assumes brokerage is flat ₹20/order, without considering minimum percentage commission thresholds or broker turnover tiers.
4. **Instantaneous Trailing Stop Modification**:
   - Assumes the broker order modification endpoint accepts continuous trailing stop adjustments without triggering rate limits (Upstox API enforces strict rate limits of 10 requests/second).

---

## 5. Unresolved Questions & Conflicts

> [!WARNING]
> ### Conflict 1: Broker API Rate Limits vs Real-time Trailing Stops
> - Upstox enforces API rate limits (typically 10 to 25 requests per second across orders and quotes).
> - If the strategy attempts to trail stop-loss orders continuously on every tick for multiple open positions, it risks hitting HTTP 429 (Rate Limit Exceeded) errors, causing stop-loss modifications to fail silently.
> - **Recommendation**: Trailing stop modifications must be throttled to bar close, or updated only when the price moves by at least 0.5 $\times$ ATR.
>
> ### Conflict 2: Limit Entry Timeout & Cancellation
> - What happens if the LIMIT BUY order placed at `Close + 0.05%` is not filled within the subsequent 5-minute candle? Does the order remain open indefinitely, or is it cancelled when the next candle closes?
> - Leaving unexecuted limit orders pending creates dangerous phantom fills when price reverses much later in the session.
