# AURA Terminal v3.5

AURA is an institutional-style market intelligence, risk and execution workspace. The default product language is English; Persian is a first-class RTL locale using the same component system and data contracts.

## v3.5 — Verified historical backtesting

- Replaced the Backtesting placeholder with a real walk-forward runner using the same AURA confluence engine as the terminal.
- Backtests accept only verified user-uploaded OHLC CSV or MT5 historical candles when a compatible MT5 runtime is connected; simulation-feed candles are never used as historical performance evidence.
- Historical Killzone evaluation uses each candle's UTC timestamp rather than current server time.
- A setup is counted only if a future candle actually touches entry. If SL and TP are both inside the same OHLC bar, AURA uses a conservative stop-first assumption.
- Backtest runs, trades, assumptions and equity curves are persisted in the ledger and available in the terminal history.
- Fees and slippage are explicitly marked as not modeled rather than hidden.

## v3.4 — Data-backed product workspace

- Signals, Auto Trade, Positions, Orders, Performance, Analytics, News Guard and Economic Calendar now have independent product views instead of falling back to Terminal.
- Added current cross-market signal-board, audited order history, open/closed position views, realized-only performance analytics and operational audit analytics.
- Auto Trade reports explicit production blockers instead of exposing a cosmetic toggle.
- News Guard and Economic Calendar report provider/configuration state without fabricating economic events.
- Performance metrics are computed only from actually closed ledger positions.

## v3.3 — Reference shell fidelity + backend-driven terminal state

- The approved three-column terminal composition now holds at standard desktop widths (1280/1366/1440), not only at 1536px+.
- Market Status now receives non-fabricated volatility and live spread metadata from the backend.
- Position sizing is previewed through `POST /api/risk/preview`, using the same broker/paper sizing logic as execution.
- Frontend risk controls follow the server-configured risk ceiling.
- Paper/simulation mode never invents a live spread or margin value.

## v3.2 — Reference UI implementation

### Exact terminal shell
- Rebuilt the terminal around the approved AURA reference: full labeled sidebar, search/account header, horizontal multi-asset watchlist, professional chart workspace, AURA Signal card, execution card, market status, News Guard, position sizing, open-position table and recent-signal rail.
- Added a dedicated mobile terminal composition instead of shrinking the desktop grid: signal summary → Entry/SL/TP → chart → timeframes → guarded execution → bottom navigation.
- English is the default language. Persian can be switched in-product and flips the full interface to RTL while price/symbol data remains LTR-safe.
- Added working Markets and Backtesting shell views using the same design language. Backtesting metrics intentionally stay empty until a historical runner is connected rather than presenting invented performance.

### Multi-asset market board
- Added `GET /api/markets` for one-call watchlist hydration.
- Expanded deterministic simulation profiles for EURUSD, GBPUSD, USDJPY, XAUUSD, BTCUSD, ETHUSD, NAS100, USOIL and SP500.
- WebSocket symbol switching remains dynamic through `WS /ws/signals?symbol=...`.

### Portfolio and execution integrity
- Retains the SQLite/WAL execution ledger, persistent paper positions, account balance, audit trail and close-at-market lifecycle introduced in v3.1.
- Paper sizing now uses the current ledger balance rather than the original starting balance.
- Paper risk/P&L assumptions are asset-aware for FX, JPY pairs, gold, oil, crypto and index simulations.
- Live mode still uses broker-native MT5 `order_calc_profit`, `order_check` and `order_send`; simulation math is never reused as live sizing.

### Risk controls
- Concurrent position limit.
- Daily AURA execution limit.
- Daily realized-loss guard.
- Duplicate-symbol protection.
- Broker-position checks before live routing.
- No fake live connectivity, fills, performance metrics or economic-news protection.

## Local run

```bash
docker compose up --build
```

Frontend: `http://localhost:3000`  
Backend: `http://localhost:8000`

AURA starts in **paper mode** and persists the ledger to the `aura-data` Docker volume.

## Environment

```bash
AURA_EXECUTION_MODE=paper
AURA_CORS_ORIGINS=http://localhost:3000
AURA_DEFAULT_SYMBOL=EURUSD
AURA_MAX_RISK_PERCENT=1.0
AURA_MT5_DEVIATION=20
AURA_DATABASE_PATH=/data/aura.db
AURA_PAPER_STARTING_BALANCE=10000
AURA_MAX_OPEN_POSITIONS=3
AURA_MAX_TRADES_PER_DAY=8
AURA_MAX_DAILY_LOSS_PERCENT=2.0
NEXT_PUBLIC_AURA_API_URL=http://localhost:8000

# Required to unlock LIVE execution on the backend.
AURA_EXECUTION_API_KEY=

# Required only on a compatible Windows MT5 execution runtime.
MT5_ACCOUNT=
MT5_PASSWORD=
MT5_SERVER=
```

## Core APIs

- `GET /api/health` — runtime, broker, capabilities and risk state.
- `GET /api/markets` — aggregated multi-asset watchlist board.
- `GET /api/market/{symbol}` — candles + structural analysis for one symbol.
- `GET /api/portfolio` — account metrics, paper positions and recent orders.
- `GET /api/audit` — durable operational audit events.
- `GET /api/backtests/capabilities` — verified historical-source availability and risk ceiling.
- `GET /api/backtests` / `GET /api/backtests/{run_id}` — persisted backtest history and detail.
- `POST /api/backtests/run` — walk-forward run from uploaded OHLC or MT5 history.
- `POST /api/trade/execute` — guarded paper/live execution.
- `POST /api/positions/{position_id}/close` — closes a paper position at current simulated/market mark.
- `WS /ws/signals?symbol=EURUSD` — realtime market, intelligence, runtime and portfolio stream.

## MT5 deployment note

The official `MetaTrader5` Python package needs a compatible Windows environment with MetaTrader 5 available. The included Linux backend container supports analytics, simulation and paper execution but **does not provide direct MT5 live execution**.

For real live deployment, isolate the MT5 adapter on a Windows worker/VM (or use a broker-native API) and put it behind an authenticated internal execution service. Broker credentials and execution privileges must never be shipped to the public browser bundle.

## Validation status

- GitHub Actions CI is enabled for backend compilation/tests and frontend TypeScript/build validation.
- The v3.3 reference-shell QA passed both backend and frontend CI jobs before merge.
- v3.4 adds coverage for realized performance aggregation and is validated by the same CI pipeline before merge.

## Next production layer

The remaining platform work is identity and infrastructure rather than visual shell work: authenticated organizations/users, broker-account ownership, PostgreSQL event storage, signed server-to-server execution, an economic-calendar provider, MT5 position reconciliation, idempotent routing, historical backtesting workers and observability.
