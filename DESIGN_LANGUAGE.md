# AURA Design Language — Institutional Terminal v3.2

## Product posture
AURA should feel like a serious execution workspace: dense but legible, precise, dark, calm and operational. It must not resemble a generic SaaS admin dashboard.

## Visual system
- Base canvas: near-black navy (`#020811`).
- Primary surfaces: deep blue-black (`#06101b` / `#07131f`).
- Borders: restrained steel-blue hairlines; depth comes from hierarchy, not heavy shadows.
- Positive / BUY / healthy runtime: AURA mint (`#2ae9bd`).
- Negative / SELL / risk: coral red (`#ff536d`).
- Interaction / selected navigation: electric blue (`#2e93ff`).
- PRO accent: restrained blue→violet gradient, isolated from core trading semantics.
- Numeric values use tabular monospace styling; UI copy uses system sans.

## Desktop information hierarchy
1. Persistent labeled navigation rail.
2. Search/account/runtime header.
3. Horizontal multi-asset watchlist.
4. Dominant chart workspace.
5. Signal + execution command stack.
6. Market/news/position-sizing state rail.
7. Persistent position table and recent execution context.

## Mobile hierarchy
Mobile is recomposed, not scaled:
1. Instrument + validated setup state.
2. Direction / confluence.
3. Entry / SL / TP.
4. Chart.
5. Timeframes.
6. Guarded execution.
7. Bottom product navigation.

## Localization
English is the product-default language. Persian is a complete RTL surface using the same components and data model. Symbols, prices, IDs and tabular market values remain direction-isolated/LTR to prevent numeric reordering.

## Trust rules
- Never render simulation as live.
- Never render a paper fill as a broker fill.
- Never invent backtest statistics, spread, economic-news safety or broker state.
- Use empty, scanning, disconnected and not-configured states as first-class product states.
