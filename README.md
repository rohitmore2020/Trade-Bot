# Trade-Bot: Automated Intraday Trading Platform for Indian NSE Equities

A modular, production-grade automated trading platform designed specifically for Indian National Stock Exchange (NSE) cash equities using the Upstox API.

Built with **correctness, determinism, reliability, auditability, and strict risk controls** as primary first-class concerns.

---

## 🏛️ Architectural Overview & Design Philosophy

Trade-Bot follows a strict **Clean Architecture (Hexagonal / Ports & Adapters)** pattern. The core business logic (domain models, indicators, strategy signals, risk controls, and portfolio tracking) is completely decoupled from external infrastructure (Upstox SDK, WebSockets, HTTP clients, databases, filesystem, and UI).

```
                      ┌─────────────────────────────────┐
                      │    CLI / Orchestration Layer    │
                      └────────────────┬────────────────┘
                                       │
                      ┌────────────────▼────────────────┐
                      │         Trading Engine          │
                      └────┬───────┬─────────┬────────┬─┘
                           │       │         │        │
            ┌──────────────┘       │         │        └──────────────┐
            ▼                      ▼         ▼                       ▼
   ┌─────────────────┐    ┌─────────────┐ ┌───────────────┐ ┌────────────────┐
   │ Market Data     │    │  Strategy   │ │ Risk Manager  │ │ Portfolio      │
   │ Aggregator      │    │  Engine     │ │ (Pre/Post)    │ │ Manager        │
   └────────┬────────┘    └──────┬──────┘ └───────┬───────┘ └───────┬────────┘
            │                    │                │                 │
            └──────────────┐     │                │                 │
                           ▼     ▼                │                 │
                      ┌─────────────────┐         │                 │
                      │  Domain Models  │◄────────┴─────────────────┘
                      │  & Contracts    │
                      └────────▲────────┘
                               │
                      ┌────────┴────────┐
                      │ ExecutionEngine │
                      └────────┬────────┘
                               │
                      ┌────────▼────────┐
                      │ IBrokerAdapter  │
                      └───┬─────────┬───┘
                          │         │
            ┌─────────────┴──┐   ┌──┴─────────────┐
            ▼                ▼   ▼                ▼
     [BacktestBroker]   [PaperBroker]    [UpstoxBroker]
```

### Key Engineering Principles

1. **Separation of Concerns**: Strategy logic produces signals; it never submits orders or talks to brokers directly. Risk management approves or rejects orders before execution.
2. **Broker as an Adapter (`IBrokerAdapter`)**: Upstox, Paper trading, and Backtesting all implement the exact same interface. The identical strategy code runs in all 3 modes without changes.
3. **Idempotency & Deduplication**: Every order request has a deterministic `client_order_id`. Retries, duplicate signals, or delayed broker callbacks never result in duplicate orders.
4. **Deterministic State Machine**: Orders progress through strict, valid state transitions (`PENDING_SUBMIT` → `SUBMITTED` → `ACKNOWLEDGED` → `FILLED` / `CANCELLED` / `REJECTED`).
5. **No Blind Trust**: An order request acknowledgment is never assumed to be filled. Positions are tracked via confirmed execution fills.
6. **Financial Safety & Circuit Breakers**: Built-in maximum daily loss, maximum loss per trade, position size limits, and time-of-day square-off enforcement (09:15 to 15:15 IST).
7. **Complete Observability**: Structured JSON logging and append-only audit trail logging for all financial events.

---

## 📁 Directory Structure

```
Trade-Bot/
├── config.example.yaml             # Example YAML configuration
├── .env.example                    # Template for environment variables
├── pyproject.toml                  # Python package and dependency metadata
├── README.md                       # Architecture and system documentation
├── trade_bot/                      # Core package
│   ├── __init__.py
│   ├── __main__.py                 # CLI entrypoint
│   ├── cli.py                      # Subcommand CLI (validate-config, backtest, paper, live)
│   ├── config/                     # Typed configuration & constants
│   │   ├── constants.py            # NSE market hours, tick sizes, holidays
│   │   └── settings.py             # Pydantic Settings models
│   ├── domain/                     # Pure domain layer (zero external dependencies)
│   │   ├── enums.py                # OrderSide, OrderStatus, OrderType, TradingMode, etc.
│   │   ├── exceptions.py           # Domain exception hierarchy
│   │   ├── models.py               # Value objects: Tick, Candle, Order, Position, Signal
│   │   └── state.py                # OrderStateMachine, PositionTracker
│   ├── data/                       # Market data handling & aggregation
│   │   ├── interfaces.py           # IMarketDataProvider, ICandleAggregator
│   │   ├── aggregator.py           # Tick to 1m/5m/15m candle aggregation
│   │   └── memory_data_feed.py     # Deterministic in-memory streaming feed
│   ├── indicators/                 # Pure mathematical & technical indicators
│   │   ├── interfaces.py           # IIndicator interface
│   │   ├── atr.py                  # Average True Range
│   │   ├── orb.py                  # Opening Range Breakout (ORB) level tracker
│   │   └── vwap.py                 # Volume-Weighted Average Price
│   ├── scanner/                    # Stock screening & universe management
│   │   ├── interfaces.py           # IStockScanner, IScannerFilter
│   │   └── universe.py             # Nifty50 / liquid equity universe management
│   ├── strategy/                   # Strategy interface & context
│   │   ├── base.py                 # IStrategy protocol, StrategyContext (read-only view)
│   │   └── registry.py             # Strategy dynamic discovery & registry
│   ├── risk/                       # Risk management layer
│   │   ├── interfaces.py           # IRiskManager, IRiskRule
│   │   ├── manager.py              # Pre-trade and Post-trade RiskManager
│   │   └── rules.py                # MaxDailyLoss, MaxPositionSize, CapitalAtRisk rules
│   ├── portfolio/                  # Portfolio & PnL accounting
│   │   ├── interfaces.py           # IPortfolioManager
│   │   └── manager.py              # Realized/unrealized P&L, position bookkeeping
│   ├── execution/                  # Execution management
│   │   ├── interfaces.py           # IExecutionEngine
│   │   ├── idempotency.py          # Idempotency token generation and check
│   │   └── engine.py               # Order routing, validation, and lifecycle
│   ├── broker/                     # Broker adapters (Ports & Adapters)
│   │   ├── interfaces.py           # IBrokerAdapter
│   │   ├── backtest_adapter.py     # Deterministic simulation with slippage & fees
│   │   ├── paper_adapter.py        # Paper broker with real-time simulated fills
│   │   └── upstox_adapter.py       # Upstox API adapter stub (live trading guarded)
│   ├── persistence/                # Storage repositories
│   │   ├── interfaces.py           # IOrderRepository, ITradeRepository, ICandleRepository
│   │   └── in_memory.py            # Thread-safe in-memory implementations
│   ├── observability/              # Structured logging & audit trails
│   │   ├── audit.py                # Financial audit logger
│   │   ├── logger.py               # Context-aware structured JSON logger
│   │   └── metrics.py              # Latency and operational metrics
│   └── orchestration/              # Engine lifecycle and dependency injection
│       ├── engine.py               # TradingEngine lifecycle coordinator
│       └── factory.py              # Dependency injection container for all modes
└── tests/                          # Comprehensive test suite
    ├── conftest.py                 # Shared test fixtures
    ├── unit/                       # Fast unit tests for all domain and logic components
    ├── integration/                # End-to-end integration and lifecycle tests
    └── architecture/               # Architectural boundary & dependency linting tests
```

---

## 🚦 Execution Modes

| Mode | Market Data | Execution | Risk Controls | Real Money |
|---|---|---|---|---|
| **BACKTEST** | Historical data (CSV/Parquet/Memory) | Simulated with Slippage & STT/Taxes | Active | ❌ No |
| **PAPER** | Live WebSocket / Polled ticks | Simulated fill matching | Active | ❌ No |
| **LIVE** | Live Upstox WebSocket Feed | Live Upstox Order API | Active (Double-checked) | ⚠️ Real Capital |

*Note: Live mode is guarded by `TRADE_BOT_ALLOW_LIVE=true` and explicit CLI confirmation.*

---

## 🛡️ Risk Management Rules

The platform enforces strict pre-trade checks:
- **Max Daily Loss**: Automatically stops trading and squares off open positions if cumulative loss exceeds the threshold.
- **Max Loss Per Trade**: Rejects orders where the distance to Stop Loss multiplied by quantity exceeds the trade risk limit.
- **Max Position Size**: Prevents overconcentration in a single stock.
- **Max Open Positions**: Limits concurrent open intraday positions.
- **Time-of-Day Restrictions**:
  - No new trades before `09:15:00 IST` or after `15:00:00 IST`.
  - Intraday mandatory square-off at `15:15:00 IST`.

---

## 🧪 Testing and Verification

Run the automated test suite:

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run with coverage
python3 -m pytest --cov=trade_bot tests/
```

Verify system configuration:

```bash
python3 -m trade_bot validate-config
```

---

## 🗺️ Phased Roadmap

- **Phase 1 (Current)**: Architecture design, modular foundation, domain models, state machines, risk management contracts, execution engine, broker adapters, structured logging, audit trails, and automated tests.
- **Phase 2**: Market data ingestion, Upstox WebSocket feed handler, historical data downloader, multi-timeframe candle aggregators.
- **Phase 3**: VWAP-ORB strategy implementation, opening range calculators, pullback filters, deterministic backtesting engine with realistic Indian tax/slippage models.
- **Phase 4**: Stock scanner, dynamic intraday universe ranking, pre-market candidate selection.
- **Phase 5**: Upstox live broker adapter integration, paper trading mode validation, live trade telemetry and emergency square-off protocols.
