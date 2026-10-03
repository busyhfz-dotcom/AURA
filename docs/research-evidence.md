# VERTEX research and validation register

VERTEX does not treat popularity, testimonials, or a creator's backtest as evidence of trading profitability. A video can suggest a testable hypothesis; its views and comments are not market features and must never increase a live confluence score. As of this change, **no externally promoted strategy has passed independent validation**, and no win probability is published.

## Data sources

| Source | Use | Limitation |
| --- | --- | --- |
| [Binance public spot klines](https://developers.binance.com/en/docs/products/spot/rest-api) and [official downloadable archive](https://github.com/binance/binance-public-data/blob/master/README.md) | Crypto OHLCV, timestamped and source-attributed; use the archive for reproducible historical tests. | Exchange-specific; spot volume is not a forex volume proxy. Archive files may be corrected; pin file checksum and ingestion date. |
| Twelve Data intraday series | Live forex/metals candles already used by VERTEX. | Free quota; do not backfill in the production scan loop. Historical access and market coverage depend on plan. |
| Finnhub economic calendar | News embargo when provider returns a healthy response. | A provider error means unknown, never “no news.” Historical tests need archived, point-in-time calendar responses before using this gate. |
| VERTEX `market_candles` | Closed 15m/1h/4h bars from existing provider calls, with symbol, source and UTC open time. | The production backend has a Railway volume mounted at `/data`; verify its health after each deployment. |

The API exposes archive coverage at `/api/research/readiness`, archived bars at `/api/data/history/{symbol}`, and a conservative forward audit at `/api/research/outcomes`. The audit distinguishes pending, unfilled, ambiguous, missing-data, win and loss cases. It reports **gross bar-based observations**, not realized broker P/L; fees, spread, slippage and intrabar order are not observable from these candles. Historical calls made before archiving started cannot be reconstructed reliably.

## Video screening

[TradingLab's popular TradingView backtesting tutorial](https://www.youtube.com/watch?v=OwvElpGjLKI) has substantial viewership and is useful as an educational starting point for formulating a test. Its video description does not provide independently auditable, out-of-sample net returns. It is **not** a validated signal source. No video strategy is enabled in the algorithm on the strength of ratings, comments, or a self-reported result.

For any future video-derived hypothesis, retain the original URL, publication date, precise entry/exit rules, market, timeframe, execution assumptions, and a versioned implementation. Reject ambiguous rules or unavailable data. Run unchanged rules on separate chronological periods and instruments; include spread, fees, slippage, nonfills, drawdown, and uncertainty. Keep the final test period untouched during selection. Publish the rejected trials as well as the winner to expose selection bias.

This standard follows the [Probability of Backtest Overfitting paper](https://escholarship.org/uc/item/4w1110bb), [QuantConnect's walk-forward guidance](https://www.quantconnect.com/docs/v2/writing-algorithms/optimization/walk-forward-optimization), [transaction-fee modeling guidance](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/transaction-fees/key-concepts), and [scikit-learn's probability calibration documentation](https://scikit-learn.org/stable/modules/calibration.html).

## Promotion gate

1. Use only bars that were fully closed at decision time. Reject stale, missing, malformed, or duplicate data.
2. Keep training, selection and final test periods chronological and disjoint. Freeze rules before the final test.
3. Record every prospective trade call and its eventual fill/outcome, including unresolved and ambiguous cases; never count a nonfill as a win. The current forward audit is the first step; it does not yet establish execution-quality outcomes.
4. Show net performance under documented, asset-specific transaction costs and stress those costs. Report sample count, drawdown and confidence interval by asset and regime.
5. Calibrate probabilities only against enough out-of-sample outcomes. Until then the API's legacy `probability_percent` field is explicitly typed `UNCALIBRATED_CONFLUENCE`, and `calibrated_probability_percent` is null.
6. Promote a candidate only if it materially beats the frozen baseline across independent periods without unacceptable drawdown. Revoke it when forward performance degrades.

## Deployment requirement

`VERTEX_DATABASE_PATH=/data/vertex.db` points at the Railway volume attached to the production backend on 2026-10-03. Back up the database and keep a single writer/replica for SQLite. If multi-replica service is needed, migrate this store to a managed database instead. The old ephemeral database cannot be relied on as historical evidence after the volume migration.
