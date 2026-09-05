# VWAP Pullback with ORB Confirmation (VWAP-ORB) Strategy Specification

## 1. Overview & Objectives
The **VWAP Pullback with ORB Confirmation (VWAP-ORB)** is a systematic intraday momentum-pullback trading strategy designed for liquid Indian National Stock Exchange (NSE) cash equities.

It combines:
1. **Benchmark Market Regime Filtering** (NIFTY trend alignment relative to VWAP).
2. **Opening Range Breakout (ORB)** reference levels (first 15 minutes: 09:15–09:30 IST).
3. **Intraday Value Anchor (VWAP)** to identify favorable pullback entries rather than chasing extended breakouts.
4. **Volume Expansion Confirmation** (institutional participation indicator).
5. **Strict Volatility-Adjusted Risk Controls** (ATR-based stop loss, dynamic trailing stop, and fixed fractional risk budgeting).

---

## 2. Stock Universe & Screening Rules

### 2.1 Eligibility Pool
- **Segment**: NSE Cash Equities.
- **Derivatives Eligibility**: Stock must be in the active NSE Futures & Options (F&O) list.
- **Price Bounds**: `Current Price ∈ [₹200.00, ₹5,000.00]`.

### 2.2 Daily Quantitative Screening Filters (Pre-Market / Opening Scan)
To construct the dynamic daily universe of **10 to 30 stocks**, an instrument must satisfy all of the following criteria:

| Filter Name | Metric / Formula | Threshold / Range |
|---|---|---|
| **Liquidity / Turnover** | 30-day (or 20-day) Average Daily Turnover | $\ge ₹100\text{ crore}$ ($₹1,000,000,000$) |
| **Volatility Window** | 20-day ATR as a percentage of price: $\frac{\text{ATR}_{20}}{\text{Close}} \times 100$ | $\in [1.5\%, 6.0\%]$ |
| **Absolute Price** | Cash equity market price | $\in [₹200.00, ₹5,000.00]$ |
| **Pre-Market Activity** | Pre-market traded volume OR Overnight gap | $\text{Pre-Market Volume} \ge 0.10 \times \text{Avg Daily Volume}$<br>OR $\frac{|\text{Open} - \text{Prev Close}|}{\text{Prev Close}} \ge 1.0\%$ |

---

## 3. Market Regime Filter
Trading direction is strictly constrained by the benchmark index (NIFTY 50 spot or front-month futures):

- **Benchmark VWAP**: Cumulative session VWAP of NIFTY starting from 09:15:00 IST.
- **Rule 1 (Bullish Regime)**: If $\text{Price}_{\text{NIFTY}} > \text{VWAP}_{\text{NIFTY}}$, **LONG trades only** are permitted. All Short signals are blocked.
- **Rule 2 (Bearish Regime)**: If $\text{Price}_{\text{NIFTY}} < \text{VWAP}_{\text{NIFTY}}$, **SHORT trades only** are permitted. All Long signals are blocked.
- **Rule 3 (Neutral / At VWAP)**: If $\text{Price}_{\text{NIFTY}} == \text{VWAP}_{\text{NIFTY}}$, **NO NEW ENTRIES** are permitted.

---

## 4. Key Indicators & Reference Levels

### 4.1 Opening Range Breakout (ORB)
- **Time Window**: 09:15:00 to 09:30:00 IST (first 15 minutes of standard session).
- **OR High ($\text{OR}_{\text{high}}$)**: $\max(\text{High}_{09:15 - 09:30})$
- **OR Low ($\text{OR}_{\text{low}}$)**: $\min(\text{Low}_{09:15 - 09:30})$
- **OR Range**: $\text{OR}_{\text{high}} - \text{OR}_{\text{low}}$

### 4.2 Intraday VWAP
- Computed continuously from 09:15:00 IST across all intraday transactions:
  $$\text{VWAP}_t = \frac{\sum_{i=1}^t (\text{Price}_i \times \text{Volume}_i)}{\sum_{i=1}^t \text{Volume}_i}$$

### 4.3 Average True Range (ATR)
- **Period**: 14 bars ($\text{ATR}_{14}$).
- Used for initial stop-loss placement and trailing stop distances.

### 4.4 Volume Moving Average
- **Period**: 10 completed candle bars ($\text{SMA}_{10}(\text{Volume})$).

---

## 5. Entry Rules

### 5.1 Trading Window
- **Permitted Entry Window**: **09:45:00 IST to 14:30:00 IST**.
- **No Entry Outside Window**: No signals evaluated before 09:45:00 IST or after 14:30:00 IST.

### 5.2 Long Entry Conditions (ALL must evaluate to TRUE)
1. **Regime Alignment**: $\text{NIFTY} > \text{VWAP}_{\text{NIFTY}}$
2. **Above Value**: $\text{Close}_{\text{bar}} > \text{VWAP}_{\text{stock}}$
3. **Pullback Confirmed**: $\text{Low}_{\text{bar}} \le \text{VWAP}_{\text{stock}} \times 1.002$ (touched or came within 0.2% of VWAP)
4. **Bullish Price Action**: $\text{Close}_{\text{bar}} > \text{Open}_{\text{bar}}$
5. **Volume Surge**: $\text{Volume}_{\text{bar}} \ge 1.5 \times \text{SMA}_{10}(\text{Volume})$
6. **ORB Confirmation**: $\text{Close}_{\text{bar}} > \text{OR}_{\text{high}}$ (or $\text{Price} > \text{OR}_{\text{high}}$)
7. **Execution Order**: Place **LIMIT BUY** at $\text{Close}_{\text{bar}} \times 1.0005$ ($\text{Close} + 0.05\%$).

### 5.3 Short Entry Conditions (Symmetric Formulation)
1. **Regime Alignment**: $\text{NIFTY} < \text{VWAP}_{\text{NIFTY}}$
2. **Below Value**: $\text{Close}_{\text{bar}} < \text{VWAP}_{\text{stock}}$
3. **Pullback Confirmed**: $\text{High}_{\text{bar}} \ge \text{VWAP}_{\text{stock}} \times 0.998$ (rallied to within 0.2% of VWAP)
4. **Bearish Price Action**: $\text{Close}_{\text{bar}} < \text{Open}_{\text{bar}}$
5. **Volume Surge**: $\text{Volume}_{\text{bar}} \ge 1.5 \times \text{SMA}_{10}(\text{Volume})$
6. **ORB Confirmation**: $\text{Close}_{\text{bar}} < \text{OR}_{\text{low}}$
7. **Execution Order**: Place **LIMIT SELL** at $\text{Close}_{\text{bar}} \times 0.9995$ ($\text{Close} - 0.05\%$).

---

## 6. Exit & Order Management Rules

### 6.1 Initial Stop Loss (SL-M Order)
- **Order Type**: Stop Loss Market (`SL-M`).
- **Long Position Stop Price**:
  $$\text{Stop Price}_{\text{Long}} = \text{Entry Price} - (1.5 \times \text{ATR}_{14})$$
- **Short Position Stop Price**:
  $$\text{Stop Price}_{\text{Short}} = \text{Entry Price} + (1.5 \times \text{ATR}_{14})$$

### 6.2 Trailing Stop Loss
- **Trail Distance**: $2.0 \times \text{ATR}_{14}$
- **Long Trailing Logic**:
  $$\text{Trail Price}_t = \max(\text{Trail Price}_{t-1}, \text{Highest Price Since Entry} - (2.0 \times \text{ATR}_{14}))$$
  The stop price only moves upwards, locking in profit as the stock advances.
- **Short Trailing Logic**:
  $$\text{Trail Price}_t = \min(\text{Trail Price}_{t-1}, \text{Lowest Price Since Entry} + (2.0 \times \text{ATR}_{14}))$$
  The stop price only moves downwards.

### 6.3 VWAP Invalidation Exit
- If the price crosses VWAP against the active position:
  - **Long Exit**: If $\text{Price} < \text{VWAP}_{\text{stock}}$ (or candle closes below VWAP).
  - **Short Exit**: If $\text{Price} > \text{VWAP}_{\text{stock}}$ (or candle closes above VWAP).
- **Execution**: Immediate Market order cancellation and position square-off.

### 6.4 Mandatory Time Exit
- At **14:30:00 IST**, any remaining open position MUST be immediately closed via a market order. All pending limit orders and stop-loss orders must be cancelled.

---

## 7. Position Sizing & Portfolio Risk Controls

### 7.1 Fixed Fractional Risk Sizing
- **Account Risk Budget Per Trade**: $0.5\%$ of Total Equity ($0.005 \times \text{Equity}$).
- **Calculated Stop Distance**: $\Delta_{\text{stop}} = 1.5 \times \text{ATR}_{14}$
- **Base Quantity**:
  $$\text{Quantity}_{\text{base}} = \left\lfloor \frac{\text{Equity} \times 0.005}{\Delta_{\text{stop}}} \right\rfloor$$

### 7.2 Capital Allocation Cap
- **Max Notional Capital Per Trade**: $20\%$ of Total Equity ($0.20 \times \text{Equity}$).
- **Max Quantity by Capital**:
  $$\text{Quantity}_{\text{cap}} = \left\lfloor \frac{\text{Equity} \times 0.20}{\text{Entry Price}} \right\rfloor$$
- **Final Order Quantity**:
  $$\text{Quantity} = \min(\text{Quantity}_{\text{base}}, \text{Quantity}_{\text{cap}})$$
  Must satisfy $\text{Quantity} \ge 1$. If 0, trade is aborted.

### 7.3 Portfolio & Session Risk Guardrails
- **Max Concurrent Open Positions**: Exactly **3**. If 3 positions are active, no new orders are permitted.
- **Max Trades Per Day**: Exactly **6** executed trades (fills) across all stocks.
- **Daily Loss Cap (Circuit Breaker)**: **2.0% of Starting Capital**. If cumulative realized + unrealized losses breach $2.0\%$, the circuit breaker halts all trading for the rest of the day and flattens active positions.

---

## 8. Open Questions / Ambiguities

> [!WARNING]
> Per engineering guidelines, the following ambiguities exist in the source text and must be formally resolved before live deployment:

1. **Candle Bar Timeframe for Signal Evaluation**:
   - The document specifies "Bullish close (close > open)", "Volume >= 1.5x 10-candle average", and "ATR(14)", but does not explicitly name the candle interval (e.g. **5-minute** vs **1-minute** vs **15-minute**). 
   - *Working Assumption for Specification*: 5-minute candles are standard for intraday ORB pullbacks.
2. **Short Entry Symmetry**:
   - The document explicitly details "Entry (LONG)" with 6 bullet points, but only mentions "NIFTY < VWAP -> SHORT only" under Regime without explicitly printing the Short bullet points.
   - *Working Assumption for Specification*: Pure symmetric inverse is defined in Section 5.3.
3. **Trailing Stop Update Frequency**:
   - Is the trailing stop evaluated tick-by-tick or on candle close?
   - Is $\text{ATR}_{14}$ fixed at entry or continuously recalculating?
   - *Working Assumption*: Evaluated on bar close with dynamic $\text{ATR}_{14}$, or tick-based high watermark.
4. **VWAP Invalidation Condition**:
   - Does "exit if price crosses VWAP against position" require a candle close across VWAP, or an instantaneous intraday tick cross?
5. **Re-entry Rules**:
   - If a stock is stopped out or exited at VWAP, can it be traded again later in the same session if another setup occurs (subject to the 6 trades/day limit)?
6. **Pre-Market Volume vs Gap Condition**:
   - "Pre-market volume >= 10% of average OR gap >= 1%": Does "average" mean 30-day average daily volume, or historical average pre-market volume?
   - Is gap calculated as `(Open - PrevClose) / PrevClose` or `abs(Open - PrevClose) / PrevClose`?

---

## 9. Implementation Checklist for Verification

- [ ] **Universe Filter**: Correctly applies ₹100 Cr turnover, ATR% [1.5%, 6%], price [₹200, ₹5000], and pre-market activity.
- [ ] **ORB Calculation**: Accurately computes 09:15–09:30 High, Low, and Range.
- [ ] **Regime Gate**: Enforces NIFTY > VWAP (Long only), NIFTY < VWAP (Short only), and halts if equal.
- [ ] **Trading Window**: Rejects signals before 09:45 and after 14:30.
- [ ] **Pullback Condition**: Validates `Low <= VWAP * 1.002` (Long) and `High >= VWAP * 0.998` (Short).
- [ ] **Volume Filter**: Validates `Volume >= 1.5 * 10-bar SMA(Volume)`.
- [ ] **ORB Filter**: Validates `Close > OR_high` (Long) and `Close < OR_low` (Short).
- [ ] **Limit Entry Order**: Sets limit price to `Close * 1.0005` (Long) and `Close * 0.9995` (Short).
- [ ] **Initial SL**: Sets SL-M at `Entry - 1.5 * ATR(14)` (Long) and `Entry + 1.5 * ATR(14)` (Short).
- [ ] **Trailing Stop**: Correctly ratchets stop at `2.0 * ATR(14)` from highest peak (never retreats).
- [ ] **VWAP Exit**: Triggers immediate exit when price crosses VWAP against position.
- [ ] **Time Exit**: Unconditionally exits open positions at 14:30:00 IST.
- [ ] **Position Sizer**: Calculates exact quantity using 0.5% risk and caps notional value at 20% capital.
- [ ] **Max Positions**: Strictly blocks order submission when 3 positions are open.
- [ ] **Max Trades**: Strictly blocks order submission when 6 trades have been executed in the day.
- [ ] **Daily Loss Cap**: Tripping 2% loss triggers circuit breaker and prevents further trading.
