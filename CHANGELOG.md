# Changelog

## 3.3.0 — Shell fidelity + backend-driven terminal state

### Frontend fidelity
- Promoted the full reference three-column terminal geometry to normal desktop widths (1280/1366/1440), instead of waiting for the 1536px `2xl` breakpoint.
- Kept the approved Chart → Signal/Execution → Status rail hierarchy intact across desktop and mobile compositions.
- Bound position sizing fields and market-status cards to backend data instead of duplicating risk math in the browser.
- Made the execution risk selector honor the backend-configured maximum risk ceiling.

### Backend terminal state
- Added broker-level market status with live spread points when MT5 is connected and non-fabricated volatility state for both live and simulation feeds.
- Added `POST /api/risk/preview` so lot sizing, risk amount, stop distance and live margin preview come from the same execution model used by the broker engine.
- Added market status to REST market snapshots and the realtime WebSocket stream.
- Added explicit max-risk metadata to health and stream payloads.

### Validation
- Added foundation coverage that verifies sizing preview matches paper execution sizing.
- Added coverage ensuring simulation mode never fabricates a live bid/ask spread.

## 3.2.0 — Reference terminal implementation

### Approved UI fidelity
- Rebuilt the terminal to match the approved AURA institutional reference layout.
- Added full labeled sidebar, account header, horizontal watchlist, chart tools, structural overlays, signal/execution stacks, status/news/sizing rail, positions table and recent execution rail.
- Added a dedicated mobile composition and bottom navigation matching the reference hierarchy.
- Added English-first localization with complete Persian RTL switching.
- Added Markets and Backtesting shell views without fabricating backtest performance.

### Market board & multi-asset simulation
- Added `GET /api/markets` aggregated board.
- Added deterministic simulation profiles for crypto, indices and oil in addition to FX and gold.
- Kept WebSocket symbol switching dynamic.

### Paper execution accuracy
- Paper position sizing now uses current ledger balance.
- Paper P&L and risk assumptions now distinguish FX/JPY, gold, oil, crypto and index simulations.

### Validation
- Backend test suite remains 6/6 passing.
- API smoke test covers health, nine-symbol market board, market snapshot and portfolio.
- TS/TSX compiler parsing passes; full Next.js build awaits npm dependency availability in the execution environment.

## 3.1.0 — Persistent command deck

### Portfolio & audit
- Added SQLite/WAL durable ledger.
- Added persistent orders, paper positions, account state and operational audit events.
- Added portfolio snapshot with balance, equity, realized/unrealized P&L and recent execution history.
- Added paper close-at-market lifecycle.

### Risk controls
- Added maximum concurrent positions.
- Added maximum AURA executions per day.
- Added daily realized-loss guard.
- Added duplicate-symbol position protection.
- Added MT5 live-position checks before live order routing.

### Live access control
- Added `AURA_EXECUTION_API_KEY` requirement for live execution.
- Added explicit audit event when live authorization fails.
- Kept live MT5 positions out of the local paper ledger so broker state remains authoritative.

### Terminal shell
- Added global account strip with equity, balance, daily P&L, position count and execution count.
- Added symbol switching for EURUSD, GBPUSD, USDJPY and XAUUSD.
- Added persistent open-position table with live mark and paper P&L.
- Added close-position controls for paper mode.
- Added risk guard metadata and recent audited execution cards.
- Refined AURA design language into a denser institutional command workspace.

### Validation
- Expanded backend test suite from 3 to 6 tests.
- Added API smoke checks for persistent execution, duplicate-symbol blocking, portfolio state, position close and audit history.
- Rechecked all TypeScript/TSX source files with the TypeScript compiler parser; dependency installation is environment-dependent.

## 3.0.0 — Foundation rebuild

- Separated paper and live execution modes.
- Removed fake MT5 connectivity and fake live fills.
- Added guarded MT5 execution and MT5-native live risk sizing.
- Removed synthetic signal fallback and hardcoded statistical confidence.
- Connected frontend to REST + WebSocket runtime data.
- Introduced AURA institutional terminal design language and explicit system-state semantics.
