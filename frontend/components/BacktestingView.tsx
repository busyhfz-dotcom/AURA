import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, BarChart3, Database, FileUp, History, Play, ShieldCheck } from "lucide-react";

const apiBase = process.env.NEXT_PUBLIC_AURA_API_URL || "http://localhost:8000";

type Bar = { time: string; open: number; high: number; low: number; close: number };
type RunSummary = {
  id: string; symbol: string; timeframe: string; source: string; bars: number;
  total_trades: number; total_return_percent?: number | null; max_drawdown_percent?: number | null; created_at: string;
};
type Trade = {
  number: number; action: "BUY" | "SELL"; entry_time: string; entry: number; sl: number; tp: number;
  exit_price: number; exit_reason: string; r_multiple: number; pnl: number;
};
type Result = {
  id?: string; symbol: string; timeframe: string; source: string; bars: number;
  metrics: {
    total_return_percent?: number | null; total_trades: number; win_rate?: number | null;
    profit_factor?: number | null; max_drawdown_percent?: number | null;
    avg_r_multiple?: number | null; expectancy_r?: number | null; sharpe_trade_returns?: number | null;
  };
  equity_curve: { timestamp: string; balance: number }[];
  trades: Trade[];
};

function metric(value?: number | null, suffix = "") {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) + suffix
    : "—";
}

function money(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "$—";
  return (value < 0 ? "-$" : "$") + Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function timeLabel(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function price(value: number, symbol: string) {
  if (symbol.includes("JPY")) return value.toFixed(3);
  if (value >= 20) return value.toFixed(2);
  return value.toFixed(5);
}

function parseCsv(text: string): Bar[] {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (lines.length < 2) throw new Error("CSV must include a header and at least one row.");
  const delimiter = lines[0].includes("\t") ? "\t" : lines[0].includes(";") ? ";" : ",";
  const headers = lines[0].split(delimiter).map(header => header.trim().toLowerCase().replace(/["']/g, ""));
  const find = (...names: string[]) => headers.findIndex(header => names.includes(header));
  const ti = find("time", "timestamp", "datetime", "date");
  const oi = find("open", "o");
  const hi = find("high", "h");
  const li = find("low", "l");
  const ci = find("close", "c");
  if ([ti, oi, hi, li, ci].some(index => index < 0)) throw new Error("CSV requires time, open, high, low and close columns.");

  const bars: Bar[] = [];
  for (const line of lines.slice(1)) {
    const cols = line.split(delimiter).map(value => value.trim().replace(/^["']|["']$/g, ""));
    const when = new Date(cols[ti]);
    const open = Number(cols[oi]);
    const high = Number(cols[hi]);
    const low = Number(cols[li]);
    const close = Number(cols[ci]);
    if (Number.isNaN(when.getTime()) || ![open, high, low, close].every(Number.isFinite)) continue;
    if (open <= 0 || high <= 0 || low <= 0 || close <= 0 || low > high || open > high || open < low || close > high || close < low) continue;
    bars.push({ time: when.toISOString(), open, high, low, close });
  }
  bars.sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());
  const normalized = [...new Map(bars.map(bar => [bar.time, bar])).values()];
  if (normalized.length < 80) throw new Error("At least 80 valid OHLC rows are required.");
  if (normalized.length > 50000) throw new Error("CSV is limited to 50,000 candles per run.");
  return normalized;
}

function EquityCurve({ values }: { values: { balance: number }[] }) {
  const points = useMemo(() => {
    if (values.length < 2) return "";
    const numbers = values.map(item => item.balance);
    const min = Math.min(...numbers);
    const max = Math.max(...numbers);
    const span = max - min || 1;
    return numbers.map((value, index) => String((index / Math.max(numbers.length - 1, 1)) * 100) + "," + String(92 - ((value - min) / span) * 82)).join(" ");
  }, [values]);

  if (!points) return <div className="flex h-full items-center justify-center text-[9px] text-[#60768b]">—</div>;
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full">
      <defs><linearGradient id="btFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2ae9bd" stopOpacity=".24" /><stop offset="100%" stopColor="#2ae9bd" stopOpacity="0" /></linearGradient></defs>
      <polygon points={"0,100 " + points + " 100,100"} fill="url(#btFill)" />
      <polyline points={points} fill="none" stroke="#2ae9bd" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function BacktestingView({ selectedSymbol, t }: { selectedSymbol: string; t: any }) {
  const [source, setSource] = useState<"UPLOAD" | "MT5">("UPLOAD");
  const [symbol, setSymbol] = useState(selectedSymbol || "EURUSD");
  const [timeframe, setTimeframe] = useState("M15");
  const [riskPercent, setRiskPercent] = useState(.5);
  const [initialBalance, setInitialBalance] = useState(10000);
  const [maxHoldBars, setMaxHoldBars] = useState(96);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [bars, setBars] = useState<Bar[]>([]);
  const [fileName, setFileName] = useState("");
  const [capabilities, setCapabilities] = useState<any>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadMeta() {
    try {
      const [capsResponse, runsResponse] = await Promise.all([
        fetch(apiBase + "/api/backtests/capabilities"),
        fetch(apiBase + "/api/backtests?limit=12"),
      ]);
      if (capsResponse.ok) setCapabilities(await capsResponse.json());
      if (runsResponse.ok) {
        const data = await runsResponse.json();
        setRuns(data.runs || []);
      }
    } catch {
      // Status remains unavailable until the API can be reached.
    }
  }

  useEffect(() => { loadMeta(); }, []);
  useEffect(() => { setSymbol(selectedSymbol || "EURUSD"); }, [selectedSymbol]);

  async function onFile(file?: File) {
    if (!file) return;
    setError(null);
    try {
      const parsed = parseCsv(await file.text());
      setBars(parsed);
      setFileName(file.name);
      if (parsed.length) {
        setStart(parsed[0].time.slice(0, 16));
        setEnd(parsed[parsed.length - 1].time.slice(0, 16));
      }
    } catch (err) {
      setBars([]);
      setFileName("");
      setError(err instanceof Error ? err.message : "Unable to parse CSV.");
    }
  }

  async function runBacktest() {
    setLoading(true);
    setError(null);
    try {
      if (source === "UPLOAD" && bars.length < 80) throw new Error(t.uploadHistoricalFirst);
      if (source === "MT5" && (!start || !end)) throw new Error(t.chooseHistoricalRange);
      const response = await fetch(apiBase + "/api/backtests/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source,
          symbol,
          timeframe,
          bars: source === "UPLOAD" ? bars : [],
          start: source === "MT5" ? new Date(start).toISOString() : null,
          end: source === "MT5" ? new Date(end).toISOString() : null,
          initial_balance: initialBalance,
          risk_percent: riskPercent,
          max_hold_bars: maxHoldBars,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Backtest rejected.");
      setResult(data);
      await loadMeta();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backtest failed.");
    } finally {
      setLoading(false);
    }
  }

  async function loadRun(id: string) {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(apiBase + "/api/backtests/" + id);
      if (!response.ok) throw new Error("Unable to load backtest run.");
      setResult(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load backtest run.");
    } finally {
      setLoading(false);
    }
  }

  const canRun = source === "UPLOAD" ? bars.length >= 80 : Boolean(capabilities?.mt5_history && start && end);

  return (
    <main className="aura-thin-scroll min-h-0 flex-1 overflow-y-auto bg-[#020b14] p-4 pb-24 lg:p-5 xl:pb-5">
      <div className="mx-auto max-w-[1180px]">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div><h1 className="text-[18px] font-semibold text-white">{t.backtestingTitle}</h1><p className="mt-1 max-w-[760px] text-[9px] leading-4 text-[#70869a]">{t.backtestingRealNote}</p></div>
          <span className="rounded-md border border-[#21465f] bg-[#071825] px-2 py-1 text-[8px] font-semibold text-[#83a6bf]">{t.noSyntheticBacktests}</span>
        </div>

        <section className="aura-panel mt-4 rounded-lg p-4">
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setSource("UPLOAD")} className={"flex items-center gap-2 rounded-md border px-3 py-2 text-[9px] " + (source === "UPLOAD" ? "border-[#2978ad] bg-[#103451] text-white" : "border-[#173047] bg-[#06131f] text-[#8195a8]")}><FileUp className="h-3.5 w-3.5" />{t.uploadCsv}</button>
            <button onClick={() => setSource("MT5")} className={"flex items-center gap-2 rounded-md border px-3 py-2 text-[9px] " + (source === "MT5" ? "border-[#2978ad] bg-[#103451] text-white" : "border-[#173047] bg-[#06131f] text-[#8195a8]")}><Database className="h-3.5 w-3.5" />{t.mt5History}</button>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <label><span className="mb-1 block text-[8px] text-[#71869b]">{t.symbol}</span><input value={symbol} onChange={event => setSymbol(event.target.value.toUpperCase())} className="aura-field force-ltr" /></label>
            <label><span className="mb-1 block text-[8px] text-[#71869b]">{t.timeframe}</span><select value={timeframe} onChange={event => setTimeframe(event.target.value)} className="aura-field"><option>M1</option><option>M5</option><option>M15</option><option>M30</option><option>H1</option><option>H4</option><option>D1</option></select></label>
            <label><span className="mb-1 block text-[8px] text-[#71869b]">{t.initialBalance}</span><input type="number" min="100" value={initialBalance} onChange={event => setInitialBalance(Math.max(100, Number(event.target.value) || 100))} className="aura-field force-ltr" /></label>
            <label><span className="mb-1 block text-[8px] text-[#71869b]">{t.riskPercent}</span><input type="number" min=".1" max={capabilities?.max_risk_percent || 1} step=".1" value={riskPercent} onChange={event => setRiskPercent(Math.min(capabilities?.max_risk_percent || 1, Math.max(.1, Number(event.target.value) || .1)))} className="aura-field force-ltr" /></label>
          </div>

          {source === "UPLOAD" ? (
            <div className="mt-3 rounded-lg border border-dashed border-[#24506d] bg-[#05121e] p-4">
              <label className="flex cursor-pointer items-center justify-between gap-4">
                <div><div className="flex items-center gap-2 text-[10px] font-medium text-white"><FileUp className="h-4 w-4 text-[#62b9ff]" />{fileName || t.chooseCsv}</div><div className="mt-1 text-[8px] text-[#60768b]">{bars.length ? bars.length.toLocaleString() + " " + t.validCandles + " · " + timeLabel(bars[0]?.time) + " → " + timeLabel(bars[bars.length - 1]?.time) : t.csvFormatNote}</div></div>
                <input type="file" accept=".csv,text/csv" className="hidden" onChange={event => onFile(event.target.files?.[0])} />
                <span className="rounded border border-[#21465f] bg-[#0b2031] px-3 py-2 text-[8px] text-[#8fb0c8]">{t.browse}</span>
              </label>
            </div>
          ) : (
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <label><span className="mb-1 block text-[8px] text-[#71869b]">{t.from}</span><input type="datetime-local" value={start} onChange={event => setStart(event.target.value)} className="aura-field force-ltr" /></label>
              <label><span className="mb-1 block text-[8px] text-[#71869b]">{t.to}</span><input type="datetime-local" value={end} onChange={event => setEnd(event.target.value)} className="aura-field force-ltr" /></label>
              {!capabilities?.mt5_history && <div className="md:col-span-2 flex items-center gap-2 rounded-md border border-[#4a3a22] bg-[#2c2215] px-3 py-2 text-[8px] text-[#e6b866]"><AlertTriangle className="h-3.5 w-3.5" />{t.mt5HistoryUnavailable}</div>}
            </div>
          )}

          <div className="mt-3 grid gap-3 md:grid-cols-[1fr_auto]">
            <label><span className="mb-1 block text-[8px] text-[#71869b]">{t.maxHoldBars}</span><input type="number" min="1" max="500" value={maxHoldBars} onChange={event => setMaxHoldBars(Math.min(500, Math.max(1, Number(event.target.value) || 1)))} className="aura-field force-ltr" /></label>
            <button onClick={runBacktest} disabled={!canRun || loading} className="aura-execute flex min-w-[150px] self-end items-center justify-center gap-2 rounded-md px-5 py-3 text-[10px] font-semibold"><Play className="h-3.5 w-3.5 fill-current" />{loading ? t.running : t.runBacktest}</button>
          </div>
          {error && <div className="mt-3 flex items-start gap-2 rounded-md border border-[#633041] bg-[#2b131d] p-3 text-[9px] text-[#ff8b9b]"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{error}</div>}
        </section>

        {result ? (
          <>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[[t.totalReturn, metric(result.metrics.total_return_percent, "%")], [t.winRate, metric(result.metrics.win_rate, "%")], [t.profitFactor, metric(result.metrics.profit_factor)], [t.totalTrades, metric(result.metrics.total_trades)]].map(([label, value], index) => (
                <div key={String(label)} className="aura-panel rounded-lg p-4"><div className="text-[8px] text-[#6f8499]">{label}</div><div className={"mt-2 aura-mono text-[22px] " + (index === 0 && (result.metrics.total_return_percent || 0) < 0 ? "text-[#ff536d]" : "text-[#2ae9bd]")}>{value}</div></div>
              ))}
            </div>
            <section className="aura-panel mt-3 rounded-lg p-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><div><div className="text-[12px] font-semibold text-white">{t.backtestEquity}</div><div className="mt-1 text-[8px] text-[#60768b]">{result.symbol} · {result.timeframe} · {result.source} · {result.bars.toLocaleString()} {t.bars}</div></div><div className="aura-mono text-[9px] text-[#8eabc2]">{result.id || "—"}</div></div>
              <div className="mt-4 h-[240px] rounded-md border border-[#173047] bg-[#03101a] p-3"><EquityCurve values={result.equity_curve} /></div>
              <div className="mt-3 flex flex-wrap gap-2 text-[8px] text-[#71869b]"><span className="aura-chip">{t.singlePosition}</span><span className="aura-chip">{t.entryFutureTouch}</span><span className="aura-chip">{t.stopFirstSameBar}</span><span className="aura-chip !border-[#563f23] !bg-[#2d2216] !text-[#e6b866]">{t.feesNotModeled}</span></div>
            </section>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[[t.maxDrawdown, metric(result.metrics.max_drawdown_percent, "%")], [t.sharpeRatio, metric(result.metrics.sharpe_trade_returns)], [t.avgRR, metric(result.metrics.avg_r_multiple, "R")], [t.expectancy, metric(result.metrics.expectancy_r, "R")]].map(([label, value]) => <div key={String(label)} className="aura-panel rounded-lg p-4"><div className="text-[8px] text-[#6f8499]">{label}</div><div className="mt-2 aura-mono text-[16px] text-white">{value}</div></div>)}
            </div>
            <section className="aura-panel mt-3 overflow-hidden rounded-lg">
              <div className="border-b border-[#173047] px-4 py-3 text-[11px] font-semibold text-white">{t.backtestTrades} <span className="text-[#60768b]">({result.trades.length})</span></div>
              {result.trades.length ? <div className="aura-thin-scroll overflow-x-auto"><table className="w-full min-w-[980px] text-left text-[8px] rtl:text-right"><thead><tr className="border-b border-[#173047] text-[#71869b]">{["#", t.time, t.type, t.entry, t.stopLoss, t.takeProfit, t.exit, t.result, t.avgRR, t.pnlDollar].map(label => <th key={String(label)} className="px-3 py-2 font-medium">{label}</th>)}</tr></thead><tbody>{result.trades.map(trade => <tr key={trade.number} className="border-b border-[#10283c] text-[#c8d5e0]"><td className="px-3 py-2 aura-mono">{trade.number}</td><td className="px-3 py-2">{timeLabel(trade.entry_time)}</td><td className={"px-3 py-2 font-semibold " + (trade.action === "BUY" ? "text-[#2ae9bd]" : "text-[#ff536d]")}>{trade.action}</td><td className="px-3 py-2 aura-mono">{price(trade.entry, result.symbol)}</td><td className="px-3 py-2 aura-mono">{price(trade.sl, result.symbol)}</td><td className="px-3 py-2 aura-mono">{price(trade.tp, result.symbol)}</td><td className="px-3 py-2 aura-mono">{price(trade.exit_price, result.symbol)}</td><td className="px-3 py-2">{trade.exit_reason}</td><td className="px-3 py-2 aura-mono">{trade.r_multiple.toFixed(2)}R</td><td className={"px-3 py-2 aura-mono " + (trade.pnl >= 0 ? "text-[#2ae9bd]" : "text-[#ff536d]")}>{money(trade.pnl)}</td></tr>)}</tbody></table></div> : <div className="p-8 text-center text-[9px] text-[#60768b]">{t.noBacktestTrades}</div>}
            </section>
          </>
        ) : (
          <section className="aura-panel mt-3 rounded-lg p-8 text-center"><BarChart3 className="mx-auto h-8 w-8 text-[#365069]" /><div className="mt-3 text-[11px] text-[#c2d0dc]">{t.noBacktestResult}</div><div className="mx-auto mt-1 max-w-[520px] text-[8px] leading-4 text-[#60768b]">{t.noBacktestResultNote}</div></section>
        )}

        <section className="aura-panel mt-3 rounded-lg p-4">
          <div className="flex items-center justify-between"><div className="flex items-center gap-2 text-[11px] font-semibold text-white"><History className="h-4 w-4 text-[#62b9ff]" />{t.backtestHistory}</div><ShieldCheck className="h-4 w-4 text-[#60768b]" /></div>
          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {runs.length ? runs.map(run => <button key={run.id} onClick={() => loadRun(run.id)} className="rounded-md border border-[#173047] bg-[#05121e] p-3 text-left hover:border-[#28577a] rtl:text-right"><div className="flex items-center justify-between"><span className="aura-mono text-[9px] text-white">{run.symbol} · {run.timeframe}</span><span className="text-[7px] text-[#60768b]">{run.source}</span></div><div className="mt-2 flex justify-between text-[8px]"><span className="text-[#71869b]">{run.total_trades} {t.trades}</span><span className={(run.total_return_percent || 0) >= 0 ? "text-[#2ae9bd]" : "text-[#ff536d]"}>{metric(run.total_return_percent, "%")}</span></div><div className="mt-1 text-[7px] text-[#526a7f]">{timeLabel(run.created_at)}</div></button>) : <div className="text-[9px] text-[#60768b]">{t.noBacktestHistory}</div>}
          </div>
        </section>
      </div>
    </main>
  );
}
