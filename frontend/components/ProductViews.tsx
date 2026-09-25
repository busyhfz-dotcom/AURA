import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Gauge,
  History,
  ListOrdered,
  Lock,
  RefreshCcw,
  ShieldCheck,
  TrendingUp,
  WalletCards,
  XCircle,
} from 'lucide-react';

const apiBase = process.env.NEXT_PUBLIC_AURA_API_URL || 'http://localhost:8000';

function money(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '$—';
  const sign = value < 0 ? '-' : '';
  return `${sign}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function price(value?: number | null, symbol = '') {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  if (symbol.includes('JPY')) return value.toFixed(3);
  if (value >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (value >= 20) return value.toFixed(2);
  return value.toFixed(5);
}

function dateLabel(value?: string | null) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function metric(value?: number | null, suffix = '') {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
}

function pnlClass(value?: number | null) {
  if ((value || 0) > 0) return 'text-[#2ae9bd]';
  if ((value || 0) < 0) return 'text-[#ff536d]';
  return 'text-[#8da1b4]';
}

function PageState({ loading, error, empty, emptyText, children }: { loading: boolean; error: string | null; empty?: boolean; emptyText?: string; children: React.ReactNode }) {
  if (loading) return <div className="aura-panel rounded-lg p-8 text-center text-[10px] text-[#8da1b4]"><RefreshCcw className="mx-auto mb-3 h-4 w-4 animate-spin" />Loading…</div>;
  if (error) return <div className="aura-panel rounded-lg border-[#633041] p-8 text-center text-[10px] text-[#ff8394]"><AlertTriangle className="mx-auto mb-3 h-4 w-4" />{error}</div>;
  if (empty) return <div className="aura-panel rounded-lg p-8 text-center text-[10px] text-[#71869b]">{emptyText || 'No data yet.'}</div>;
  return <>{children}</>;
}

function PageHeader({ icon: Icon, title, subtitle, badge }: { icon: any; title: string; subtitle: string; badge?: string }) {
  return <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
    <div className="flex items-start gap-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#1a4361] bg-[#071a2a] text-[#62b9ff]"><Icon className="h-4 w-4" /></div>
      <div><h1 className="text-[18px] font-semibold text-white">{title}</h1><p className="mt-1 max-w-[680px] text-[9px] leading-4 text-[#70869a]">{subtitle}</p></div>
    </div>
    {badge && <span className="rounded-md border border-[#1b3e58] bg-[#071725] px-2 py-1 text-[8px] font-semibold text-[#8eabc2]">{badge}</span>}
  </div>;
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="aura-thin-scroll min-h-0 flex-1 overflow-y-auto bg-[#020b14] p-4 pb-24 lg:p-5 xl:pb-5"><div className="mx-auto max-w-[1160px]">{children}</div></main>;
}

type SignalRow = {
  symbol: string;
  source: string;
  market_status?: { last_price?: number | null; volatility_state?: string; volatility_percent?: number | null };
  signal: {
    status: 'A_PLUS_SETUP' | 'SCANNING' | 'WAITING_FOR_DATA';
    action?: 'BUY' | 'SELL';
    confluence_score: number;
    rr?: string;
    checklist: { sweep: boolean; displacement: boolean; fvg_midpoint: boolean; killzone_active: boolean };
  };
};

export function SignalsView({ t, onOpenSymbol }: { t: any; onOpenSymbol: (symbol: string) => void }) {
  const [rows, setRows] = useState<SignalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const response = await fetch(`${apiBase}/api/signals`);
      if (!response.ok) throw new Error('Unable to load signal board.');
      const data = await response.json();
      setRows(data.items || []);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to load signal board.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  return <Shell>
    <PageHeader icon={Activity} title={t.signals} subtitle={t.signalsPageNote} badge="LIVE ENGINE STATE" />
    <PageState loading={loading} error={error} empty={!rows.length} emptyText={t.noSetup}>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {rows.map(row => {
          const ready = row.signal.status === 'A_PLUS_SETUP';
          const passed = [row.signal.checklist.sweep, row.signal.checklist.displacement, row.signal.checklist.fvg_midpoint, row.signal.checklist.killzone_active].filter(Boolean).length;
          return <button key={row.symbol} onClick={() => onOpenSymbol(row.symbol)} className="aura-panel rounded-lg p-4 text-left transition hover:-translate-y-0.5 hover:border-[#2d668f] rtl:text-right">
            <div className="flex items-center justify-between"><span className="aura-mono text-[12px] font-semibold text-white">{row.symbol}</span><span className={`rounded px-2 py-1 text-[8px] font-semibold ${ready ? 'bg-[#0b493a] text-[#2ae9bd]' : 'bg-[#162a3d] text-[#8ea4b8]'}`}>{ready ? t.setup : row.signal.status === 'SCANNING' ? t.scanning : t.waiting}</span></div>
            <div className="mt-4 flex items-end justify-between"><div><div className="text-[8px] text-[#6f8499]">{t.price}</div><div className="mt-1 aura-mono text-[16px] text-white">{price(row.market_status?.last_price, row.symbol)}</div></div><div className="text-right rtl:text-left"><div className="text-[8px] text-[#6f8499]">{t.confluenceScore}</div><div className="mt-1 aura-mono text-[18px] text-[#2ae9bd]">{Math.round(row.signal.confluence_score || 0)}<span className="text-[9px] text-[#60768b]">/100</span></div></div></div>
            <div className="mt-4 grid grid-cols-2 gap-2 text-[8px]"><div className="rounded bg-[#06131f] p-2"><div className="text-[#60768b]">{t.type}</div><div className={`mt-1 font-semibold ${row.signal.action === 'SELL' ? 'text-[#ff536d]' : row.signal.action === 'BUY' ? 'text-[#2ae9bd]' : 'text-[#8499ad]'}`}>{row.signal.action || '—'}</div></div><div className="rounded bg-[#06131f] p-2"><div className="text-[#60768b]">{t.riskReward}</div><div className="mt-1 aura-mono text-[#c6d3df]">{row.signal.rr || '—'}</div></div></div>
            <div className="mt-3 flex items-center justify-between text-[8px] text-[#647b91]"><span>{passed}/4 {t.conditionsPassed}</span><span>{row.source}</span></div>
          </button>;
        })}
      </div>
    </PageState>
  </Shell>;
}

type AutoTradeState = {
  enabled: boolean;
  ready: boolean;
  blockers: string[];
  broker: { connected: boolean; provider: string; reason?: string | null };
  news_guard: { configured: boolean; active: boolean; message?: string };
  risk_guard: { state: string };
};

export function AutoTradeView({ t }: { t: any }) {
  const [data, setData] = useState<AutoTradeState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${apiBase}/api/auto-trade`).then(async response => {
      if (!response.ok) throw new Error('Unable to load Auto Trade state.');
      return response.json();
    }).then(value => alive && setData(value)).catch(err => alive && setError(err.message)).finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, []);
  const blockerLabel = (code: string) => ({
    LIVE_MODE_REQUIRED: t.liveModeRequired,
    BROKER_NOT_CONNECTED: t.brokerNotConnected,
    EXECUTION_KEY_REQUIRED: t.executionKeyRequired,
    NEWS_GUARD_REQUIRED: t.newsGuardRequired,
    NEWS_GUARD_UNHEALTHY: t.newsGuardUnhealthy,
    NEWS_EMBARGO_ACTIVE: t.newsEmbargoActive,
    AUTOPILOT_WORKER_NOT_DEPLOYED: t.workerNotDeployed,
  } as Record<string, string>)[code] || code;

  return <Shell>
    <PageHeader icon={Bot} title={t.autoTrade} subtitle={t.autoTradePageNote} badge={data?.ready ? 'READY' : 'GUARDED'} />
    <PageState loading={loading} error={error} empty={!data}>
      {data && <div className="grid gap-3 lg:grid-cols-[1.1fr_.9fr]">
        <section className="aura-panel rounded-lg p-5">
          <div className="flex items-center justify-between"><div><div className="text-[12px] font-semibold text-white">{t.autoExecutionReadiness}</div><div className="mt-1 text-[9px] text-[#70869a]">{t.autoTradeSafetyNote}</div></div><div className={`flex h-10 w-10 items-center justify-center rounded-full ${data.ready ? 'bg-[#0b493a] text-[#2ae9bd]' : 'bg-[#321e2a] text-[#ff7085]'}`}>{data.ready ? <CheckCircle2 className="h-5 w-5" /> : <Lock className="h-5 w-5" />}</div></div>
          <div className="mt-5 space-y-2">{data.blockers.map(code => <div key={code} className="flex items-center gap-3 rounded-md border border-[#173047] bg-[#05121e] px-3 py-2.5"><XCircle className="h-3.5 w-3.5 shrink-0 text-[#ff6d83]" /><div><div className="aura-mono text-[9px] text-[#9aafc1]">{code}</div><div className="mt-0.5 text-[9px] text-[#c1cfdb]">{blockerLabel(code)}</div></div></div>)}</div>
        </section>
        <section className="aura-panel rounded-lg p-5">
          <div className="text-[12px] font-semibold text-white">{t.systemIntegrity}</div>
          <div className="mt-4 space-y-3 text-[9px]">
            <div className="flex items-center justify-between border-b border-[#173047] pb-3"><span className="text-[#71869b]">{t.broker}</span><span className={data.broker.connected ? 'text-[#2ae9bd]' : 'text-[#ff6d83]'}>{data.broker.connected ? t.connected : t.offline}</span></div>
            <div className="flex items-center justify-between border-b border-[#173047] pb-3"><span className="text-[#71869b]">{t.newsGuard}</span><span className={data.news_guard.configured ? 'text-[#2ae9bd]' : 'text-[#e6b866]'}>{data.news_guard.configured ? t.safe : t.notConfigured}</span></div>
            <div className="flex items-center justify-between"><span className="text-[#71869b]">{t.riskGuard}</span><span className={data.risk_guard.state === 'READY' ? 'text-[#2ae9bd]' : 'text-[#ff6d83]'}>{data.risk_guard.state}</span></div>
          </div>
          <button disabled className="aura-execute mt-5 w-full rounded-md py-3 text-[10px] font-semibold">{t.autoTradeLocked}</button>
        </section>
      </div>}
    </PageState>
  </Shell>;
}

type PositionRow = {
  id: string; symbol: string; action: 'BUY' | 'SELL'; lots: number; entry_price: number; exit_price?: number | null;
  mark_price?: number | null; sl: number; tp: number; realized_pnl?: number; unrealized_pnl?: number; opened_at: string; closed_at?: string | null;
};

export function PositionsView({ t }: { t: any }) {
  const [open, setOpen] = useState<PositionRow[]>([]);
  const [closed, setClosed] = useState<PositionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/positions?closed_limit=100`);
      if (!response.ok) throw new Error('Unable to load positions.');
      const data = await response.json();
      setOpen(data.open || []); setClosed(data.closed || []);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to load positions.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const close = async (id: string) => {
    setClosing(id);
    try {
      const response = await fetch(`${apiBase}/api/positions/${id}/close`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Close rejected.');
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Close rejected.'); }
    finally { setClosing(null); }
  };

  const table = (rows: PositionRow[], isClosed: boolean) => <div className="aura-thin-scroll overflow-x-auto"><table className="w-full min-w-[900px] text-left text-[9px] rtl:text-right"><thead><tr className="border-b border-[#173047] text-[#71869b]">{[t.symbol,t.type,t.lot,t.entry,isClosed ? t.exit : t.current,t.stopLoss,t.takeProfit,isClosed ? t.realizedPnl : t.openPnl,t.actions].map(label => <th key={label} className="px-3 py-2 font-medium">{label}</th>)}</tr></thead><tbody>{rows.map(row => {
    const pnl = isClosed ? row.realized_pnl : row.unrealized_pnl;
    return <tr key={row.id} className="border-b border-[#10283c] text-[#d3dee8]"><td className="px-3 py-2 aura-mono text-white">{row.symbol}</td><td className={`px-3 py-2 font-semibold ${row.action === 'BUY' ? 'text-[#2ae9bd]' : 'text-[#ff536d]'}`}>{row.action}</td><td className="px-3 py-2 aura-mono">{row.lots.toFixed(2)}</td><td className="px-3 py-2 aura-mono">{price(row.entry_price,row.symbol)}</td><td className="px-3 py-2 aura-mono">{price(isClosed ? row.exit_price : row.mark_price,row.symbol)}</td><td className="px-3 py-2 aura-mono">{price(row.sl,row.symbol)}</td><td className="px-3 py-2 aura-mono">{price(row.tp,row.symbol)}</td><td className={`px-3 py-2 aura-mono ${pnlClass(pnl)}`}>{money(pnl)}</td><td className="px-3 py-2">{isClosed ? <span className="text-[#60768b]">{dateLabel(row.closed_at)}</span> : <button disabled={closing === row.id} onClick={() => close(row.id)} className="rounded border border-[#24435d] bg-[#102238] px-3 py-1 text-[8px] text-[#c0cfdb] hover:text-white disabled:opacity-50">{closing === row.id ? '…' : t.close}</button>}</td></tr>;
  })}</tbody></table></div>;

  return <Shell>
    <PageHeader icon={WalletCards} title={t.positions} subtitle={t.positionsPageNote} />
    <PageState loading={loading} error={error}>
      <div className="space-y-3">
        <section className="aura-panel overflow-hidden rounded-lg"><div className="border-b border-[#173047] px-4 py-3 text-[11px] font-semibold text-white">{t.openPositions} <span className="text-[#60768b]">({open.length})</span></div>{open.length ? table(open,false) : <div className="p-8 text-center text-[9px] text-[#60768b]">{t.noPositions}</div>}</section>
        <section className="aura-panel overflow-hidden rounded-lg"><div className="border-b border-[#173047] px-4 py-3 text-[11px] font-semibold text-white">{t.closedPositions} <span className="text-[#60768b]">({closed.length})</span></div>{closed.length ? table(closed,true) : <div className="p-8 text-center text-[9px] text-[#60768b]">{t.noClosedPositions}</div>}</section>
      </div>
    </PageState>
  </Shell>;
}

type OrderRow = { id: string; mode: string; status: string; symbol: string; action: 'BUY' | 'SELL'; lots: number; entry_price: number; sl: number; tp: number; risk_percent: number; created_at: string };

export function OrdersView({ t }: { t: any }) {
  const [rows, setRows] = useState<OrderRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${apiBase}/api/orders?limit=50`).then(async response => { if (!response.ok) throw new Error('Unable to load orders.'); return response.json(); }).then(data => alive && setRows(data.orders || [])).catch(err => alive && setError(err.message)).finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, []);
  return <Shell>
    <PageHeader icon={ListOrdered} title={t.orders} subtitle={t.ordersPageNote} />
    <PageState loading={loading} error={error} empty={!rows.length} emptyText={t.noOrders}>
      <section className="aura-panel overflow-hidden rounded-lg"><div className="aura-thin-scroll overflow-x-auto"><table className="w-full min-w-[880px] text-left text-[9px] rtl:text-right"><thead><tr className="border-b border-[#173047] text-[#71869b]">{[t.orderId,t.symbol,t.type,t.mode,t.lot,t.entry,t.riskPercent,t.status,t.time].map(label => <th key={label} className="px-3 py-3 font-medium">{label}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.id} className="border-b border-[#10283c] text-[#d3dee8]"><td className="px-3 py-2 aura-mono text-[#8eb5d3]">{row.id}</td><td className="px-3 py-2 aura-mono text-white">{row.symbol}</td><td className={`px-3 py-2 font-semibold ${row.action === 'BUY' ? 'text-[#2ae9bd]' : 'text-[#ff536d]'}`}>{row.action}</td><td className="px-3 py-2 uppercase text-[#88a0b4]">{row.mode}</td><td className="px-3 py-2 aura-mono">{row.lots.toFixed(2)}</td><td className="px-3 py-2 aura-mono">{price(row.entry_price,row.symbol)}</td><td className="px-3 py-2 aura-mono">{row.risk_percent.toFixed(2)}%</td><td className="px-3 py-2"><span className="rounded bg-[#0b493a] px-2 py-1 text-[7px] text-[#2ae9bd]">{row.status}</span></td><td className="px-3 py-2 text-[#6f8499]">{dateLabel(row.created_at)}</td></tr>)}</tbody></table></div></section>
    </PageState>
  </Shell>;
}

type PerformanceData = {
  closed_trades: number; wins: number; losses: number; breakeven: number; win_rate?: number | null;
  gross_profit: number; gross_loss: number; net_realized: number; profit_factor?: number | null; avg_win?: number | null;
  avg_loss?: number | null; expectancy?: number | null; max_drawdown_percent?: number | null;
  equity_curve: { timestamp: string; balance: number }[];
};

function EquityCurve({ values }: { values: { balance: number }[] }) {
  const points = useMemo(() => {
    if (!values.length) return '';
    const numbers = values.map(item => item.balance);
    const min = Math.min(...numbers), max = Math.max(...numbers), span = max - min || 1;
    return numbers.map((value,index) => `${(index / Math.max(numbers.length - 1, 1)) * 100},${88 - ((value-min)/span)*72}`).join(' ');
  }, [values]);
  if (!points) return <div className="flex h-full items-center justify-center text-[9px] text-[#60768b]">No closed-trade equity data yet.</div>;
  return <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full"><line x1="0" y1="88" x2="100" y2="88" stroke="rgba(89,132,170,.18)" strokeWidth=".5" /><polyline points={points} fill="none" stroke="#2ae9bd" strokeWidth="1.4" vectorEffect="non-scaling-stroke" /></svg>;
}

export function PerformanceView({ t }: { t: any }) {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading,setLoading]=useState(true); const [error,setError]=useState<string|null>(null);
  useEffect(()=>{let alive=true;fetch(`${apiBase}/api/performance`).then(async r=>{if(!r.ok)throw new Error('Unable to load performance.');return r.json();}).then(v=>alive&&setData(v)).catch(e=>alive&&setError(e.message)).finally(()=>alive&&setLoading(false));return()=>{alive=false};},[]);
  return <Shell><PageHeader icon={TrendingUp} title={t.performance} subtitle={t.performancePageNote} badge={t.realizedOnly} /><PageState loading={loading} error={error} empty={!data}>
    {data && <><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[[t.netRealized,money(data.net_realized),pnlClass(data.net_realized)],[t.winRate,metric(data.win_rate,'%'),'text-[#2ae9bd]'],[t.profitFactor,metric(data.profit_factor),'text-white'],[t.maxDrawdown,metric(data.max_drawdown_percent,'%'),'text-[#ffb14a]']].map(([label,value,cls])=><div key={String(label)} className="aura-panel rounded-lg p-4"><div className="text-[8px] text-[#6f8499]">{label}</div><div className={`mt-2 aura-mono text-[22px] ${cls}`}>{value}</div></div>)}</div><section className="aura-panel mt-3 rounded-lg p-4"><div className="flex items-center justify-between"><div className="text-[12px] font-semibold text-white">{t.equityCurve}</div><div className="aura-mono text-[9px] text-[#71869b]">{data.closed_trades} {t.closedTrades}</div></div><div className="mt-4 h-[230px] rounded border border-[#173047] bg-[#03101a] p-3"><EquityCurve values={data.equity_curve || []} /></div></section><div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[[t.wins,data.wins],[t.losses,data.losses],[t.avgWin,money(data.avg_win)],[t.expectancy,money(data.expectancy)]].map(([label,value])=><div key={String(label)} className="aura-panel rounded-lg p-4"><div className="text-[8px] text-[#6f8499]">{label}</div><div className="mt-2 aura-mono text-[16px] text-white">{String(value ?? '—')}</div></div>)}</div></>}
  </PageState></Shell>;
}

export function AnalyticsView({ t }: { t: any }) {
  const [data,setData]=useState<any>(null); const [loading,setLoading]=useState(true); const [error,setError]=useState<string|null>(null);
  useEffect(()=>{let alive=true;fetch(`${apiBase}/api/analytics`).then(async r=>{if(!r.ok)throw new Error('Unable to load analytics.');return r.json();}).then(v=>alive&&setData(v)).catch(e=>alive&&setError(e.message)).finally(()=>alive&&setLoading(false));return()=>{alive=false};},[]);
  return <Shell><PageHeader icon={Gauge} title={t.analytics} subtitle={t.analyticsPageNote} /><PageState loading={loading} error={error} empty={!data}>{data&&<div className="grid gap-3 lg:grid-cols-[1fr_.8fr]"><div className="space-y-3"><div className="grid gap-3 sm:grid-cols-3">{[[t.equity,money(data.account.equity)],[t.openPnl,money(data.account.unrealized_pnl)],[t.realizedToday,money(data.account.realized_today)]].map(([label,value])=><div key={String(label)} className="aura-panel rounded-lg p-4"><div className="text-[8px] text-[#6f8499]">{label}</div><div className="mt-2 aura-mono text-[17px] text-white">{value}</div></div>)}</div><section className="aura-panel rounded-lg p-4"><div className="text-[12px] font-semibold text-white">{t.riskGuard}</div><div className="mt-4 grid gap-3 sm:grid-cols-3 text-[9px]"><div><div className="text-[#6f8499]">{t.status}</div><div className="mt-1 text-[#2ae9bd]">{data.risk_guard.state}</div></div><div><div className="text-[#6f8499]">{t.openPositions}</div><div className="mt-1 aura-mono text-white">{data.risk_guard.metrics.open_positions}/{data.risk_guard.max_open_positions}</div></div><div><div className="text-[#6f8499]">{t.tradesToday}</div><div className="mt-1 aura-mono text-white">{data.risk_guard.metrics.trades_today}/{data.risk_guard.max_trades_per_day}</div></div></div></section></div><section className="aura-panel rounded-lg p-4"><div className="flex items-center gap-2 text-[12px] font-semibold text-white"><History className="h-4 w-4 text-[#62b9ff]" />{t.auditTrail}</div><div className="mt-4 space-y-2">{(data.recent_audit||[]).map((event:any)=><div key={event.id} className="rounded border border-[#153047] bg-[#05121e] p-2.5"><div className="flex items-center justify-between gap-2"><span className="aura-mono text-[8px] text-[#8eabc2]">{event.event_type}</span><span className="text-[7px] text-[#60768b]">{dateLabel(event.created_at)}</span></div><div className="mt-1 text-[9px] leading-4 text-[#c2d0dc]">{event.message}</div></div>)}</div></section></div>}</PageState></Shell>;
}

type CalendarEvent = {
  event: string;
  country?: string | null;
  currency?: string | null;
  time: string;
  impact: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN' | string;
  actual?: string | number | null;
  estimate?: string | number | null;
  previous?: string | number | null;
  unit?: string | null;
};

type CalendarData = {
  configured: boolean;
  provider?: string | null;
  provider_error?: string | null;
  guard_active: boolean;
  safe?: boolean;
  message?: string | null;
  embargo_before_minutes?: number | null;
  embargo_after_minutes?: number | null;
  blocking_events?: CalendarEvent[];
  events: CalendarEvent[];
};

function impactClass(impact?: string) {
  if (impact === 'HIGH') return 'border-[#713342] bg-[#2b141c] text-[#ff758a]';
  if (impact === 'MEDIUM') return 'border-[#5d4c2e] bg-[#241d10] text-[#e6bc72]';
  if (impact === 'LOW') return 'border-[#1b5146] bg-[#0b2823] text-[#64d5ba]';
  return 'border-[#254057] bg-[#0a1a27] text-[#8ca4b8]';
}

function impactLabel(impact: string, t: any) {
  if (impact === 'HIGH') return t.highImpact;
  if (impact === 'MEDIUM') return t.mediumImpact;
  if (impact === 'LOW') return t.lowImpact;
  return impact || '—';
}

function CalendarEventList({ events, t }: { events: CalendarEvent[]; t: any }) {
  if (!events.length) return <div className="flex min-h-[220px] items-center justify-center text-center"><div><CalendarDays className="mx-auto h-7 w-7 text-[#365069]" /><div className="mt-3 text-[10px] text-[#b0c0cd]">{t.noCalendarEvents}</div><div className="mt-1 max-w-[360px] text-[8px] leading-4 text-[#60768b]">{t.calendarProviderRequired}</div></div></div>;
  return <div className="mt-4 space-y-2">{events.map((event,index) => <div key={`${event.time}-${event.event}-${index}`} className="grid gap-3 rounded-md border border-[#173047] bg-[#05121e] p-3 sm:grid-cols-[110px_70px_minmax(0,1fr)_auto] sm:items-center">
    <div className="force-ltr">
      <div className="aura-mono text-[9px] text-white">{new Date(event.time).toLocaleDateString()}</div>
      <div className="mt-1 aura-mono text-[8px] text-[#71869b]">{new Date(event.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
    </div>
    <div><span className="aura-mono rounded bg-[#10263a] px-2 py-1 text-[8px] text-[#b8c9d7]">{event.currency || event.country || '—'}</span></div>
    <div className="min-w-0"><div className="truncate text-[10px] font-medium text-[#dbe6ef]">{event.event}</div><div className="mt-1 flex flex-wrap gap-3 text-[8px] text-[#71869b]"><span>{t.actual}: <b className="font-normal text-[#b7c6d3]">{event.actual ?? '—'}</b></span><span>{t.estimate}: <b className="font-normal text-[#b7c6d3]">{event.estimate ?? '—'}</b></span><span>{t.previous}: <b className="font-normal text-[#b7c6d3]">{event.previous ?? '—'}</b></span></div></div>
    <div><span className={`rounded border px-2 py-1 text-[8px] font-semibold ${impactClass(event.impact)}`}>{impactLabel(event.impact,t)}</span></div>
  </div>)}</div>;
}

export function NewsGuardView({ t }: { t: any }) {
  const [data,setData]=useState<CalendarData|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState<string|null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/calendar?hours=48`);
      if (!response.ok) throw new Error('Unable to load News Guard state.');
      setData(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load News Guard state.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const stateClass = data?.provider_error ? 'text-[#ff536d]' : data?.guard_active ? 'text-[#ff536d]' : data?.safe ? 'text-[#2ae9bd]' : 'text-[#e6b866]';
  const stateLabel = data?.provider_error ? t.providerError : data?.guard_active ? t.embargoActive : data?.safe ? t.safe : t.notConfigured;

  return <Shell>
    <PageHeader icon={ShieldCheck} title={t.newsGuard} subtitle={t.newsGuardPageNote} badge={data?.safe ? t.guardOperational : data?.guard_active ? t.embargoActive : t.notConfigured} />
    <PageState loading={loading} error={error} empty={!data}>
      {data&&<div className="grid gap-3 lg:grid-cols-[1fr_.8fr]">
        <section className="aura-panel rounded-lg p-5">
          <div className="flex items-center justify-between gap-4">
            <div><div className="text-[12px] font-semibold text-white">{t.newsGuard}</div><div className="mt-1 text-[9px] leading-4 text-[#70869a]">{data.message || t.newsPending}</div></div>
            <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${data.guard_active || data.provider_error ? 'bg-[#321e2a] text-[#ff7085]' : data.safe ? 'bg-[#0b493a] text-[#2ae9bd]' : 'bg-[#3c2f1b] text-[#e6b866]'}`}><ShieldCheck className="h-5 w-5" /></div>
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <div className="rounded border border-[#173047] bg-[#05121e] p-3"><div className="text-[8px] text-[#71869b]">{t.provider}</div><div className="mt-1 aura-mono text-[10px] text-white">{data.provider || '—'}</div></div>
            <div className="rounded border border-[#173047] bg-[#05121e] p-3"><div className="text-[8px] text-[#71869b]">{t.status}</div><div className={`mt-1 text-[10px] ${stateClass}`}>{stateLabel}</div></div>
          </div>
          {data.provider_error && <div className="mt-3 rounded border border-[#633041] bg-[#24111a] p-3 text-[8px] leading-4 text-[#ff8394]"><AlertTriangle className="mr-1.5 inline h-3.5 w-3.5 rtl:ml-1.5 rtl:mr-0" />{data.provider_error}</div>}
          <div className="mt-3 rounded border border-[#173047] bg-[#05121e] p-3 text-[8px] text-[#8298aa]">
            Embargo: <span className="aura-mono text-[#c0cfdb]">-{data.embargo_before_minutes ?? '—'}m / +{data.embargo_after_minutes ?? '—'}m</span>
          </div>
        </section>
        <section className="aura-panel rounded-lg p-5">
          <div className="flex items-center justify-between"><div className="text-[12px] font-semibold text-white">{t.systemIntegrity}</div><button onClick={load} className="rounded border border-[#173047] p-1.5 text-[#71869b] hover:text-white"><RefreshCcw className="h-3.5 w-3.5" /></button></div>
          <div className="mt-4 space-y-3 text-[9px]">
            <div className="flex items-center justify-between border-b border-[#173047] pb-3"><span className="text-[#71869b]">{t.provider}</span><span className={data.configured && !data.provider_error ? 'text-[#2ae9bd]' : 'text-[#e6b866]'}>{data.configured && !data.provider_error ? t.connected : data.provider_error ? t.providerError : t.notConfigured}</span></div>
            <div className="flex items-center justify-between border-b border-[#173047] pb-3"><span className="text-[#71869b]">{t.newsGuard}</span><span className={stateClass}>{stateLabel}</span></div>
            <div className="flex items-center justify-between"><span className="text-[#71869b]">{t.upcomingEvents}</span><span className="aura-mono text-white">{data.events.length}</span></div>
          </div>
          {!!data.blocking_events?.length && <div className="mt-4 rounded-md border border-[#713342] bg-[#2b141c] p-3"><div className="text-[9px] font-semibold text-[#ff758a]">{t.embargoActive}</div><div className="mt-2 space-y-1">{data.blocking_events.map((event,index)=><div key={index} className="text-[8px] text-[#d7a7b0]">{event.currency || '—'} · {event.event}</div>)}</div></div>}
        </section>
      </div>}
    </PageState>
  </Shell>;
}

export function CalendarView({ t }: { t: any }) {
  const [data,setData]=useState<CalendarData|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState<string|null>(null);

  const load=useCallback(async()=>{
    setError(null);
    try {
      const response=await fetch(`${apiBase}/api/calendar?hours=72`);
      if(!response.ok) throw new Error('Unable to load calendar state.');
      setData(await response.json());
    } catch(err) {
      setError(err instanceof Error ? err.message : 'Unable to load calendar state.');
    } finally {
      setLoading(false);
    }
  },[]);

  useEffect(()=>{load();const id=setInterval(load,120_000);return()=>clearInterval(id);},[load]);

  return <Shell>
    <PageHeader icon={CalendarDays} title={t.calendar} subtitle={t.calendarPageNote} badge={data?.configured ? (data.provider || 'CONNECTED').toUpperCase() : t.notConfigured} />
    <PageState loading={loading} error={error} empty={!data}>
      {data&&<div className="grid gap-3 lg:grid-cols-[.7fr_1.3fr]">
        <section className="aura-panel rounded-lg p-5">
          <div className="flex items-center justify-between"><div className="text-[12px] font-semibold text-white">{t.newsGuard}</div><ShieldCheck className={`h-5 w-5 ${data.guard_active || data.provider_error ? 'text-[#ff536d]' : data.safe ? 'text-[#2ae9bd]' : 'text-[#e6b866]'}`} /></div>
          <div className="mt-4 text-[9px] leading-5 text-[#90a4b6]">{data.message || t.newsPending}</div>
          <div className="mt-4 rounded-md border border-[#173047] bg-[#05121e] p-3 text-[9px]">
            <div className="flex justify-between"><span className="text-[#71869b]">{t.provider}</span><span className="aura-mono text-white">{data.provider || '—'}</span></div>
            <div className="mt-3 flex justify-between"><span className="text-[#71869b]">{t.status}</span><span className={data.guard_active || data.provider_error ? 'text-[#ff536d]' : data.safe ? 'text-[#2ae9bd]' : 'text-[#e6b866]'}>{data.provider_error ? t.providerError : data.guard_active ? t.embargoActive : data.safe ? t.safe : t.notConfigured}</span></div>
            <div className="mt-3 flex justify-between"><span className="text-[#71869b]">{t.upcomingEvents}</span><span className="aura-mono text-white">{data.events.length}</span></div>
          </div>
          {data.provider_error && <div className="mt-3 rounded border border-[#633041] bg-[#24111a] p-3 text-[8px] leading-4 text-[#ff8394]">{data.provider_error}</div>}
        </section>
        <section className="aura-panel rounded-lg p-5">
          <div className="flex items-center justify-between"><div className="text-[12px] font-semibold text-white">{t.upcomingEvents}</div><Clock3 className="h-4 w-4 text-[#60768b]" /></div>
          <CalendarEventList events={data.events} t={t} />
        </section>
      </div>}
    </PageState>
  </Shell>;
}

