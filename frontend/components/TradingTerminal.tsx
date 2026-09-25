import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createChart, IChartApi, ISeriesApi } from 'lightweight-charts';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  Bot,
  CalendarDays,
  CandlestickChart,
  ChevronDown,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Crosshair,
  Gauge,
  Globe2,
  History,
  Languages,
  Layers3,
  LineChart,
  ListOrdered,
  Menu,
  MoreHorizontal,
  Newspaper,
  PanelLeftClose,
  Play,
  Plus,
  Radio,
  RefreshCcw,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Target,
  TrendingUp,
  WalletCards,
  X,
  Zap,
} from 'lucide-react';
import { Language, translations } from '../locales/dictionary';
import BacktestingView from './BacktestingView';
import {
  AnalyticsView,
  AutoTradeView,
  CalendarView,
  NewsGuardView,
  OrdersView,
  PerformanceView,
  PositionsView,
  SignalsView,
} from './ProductViews';

type View = 'terminal' | 'markets' | 'signals' | 'auto-trade' | 'positions' | 'orders' | 'performance' | 'backtesting' | 'news-guard' | 'analytics' | 'calendar';
type StreamState = 'connected' | 'reconnecting' | 'offline';

type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
};

type Checklist = {
  sweep: boolean;
  displacement: boolean;
  fvg_midpoint: boolean;
  killzone_active: boolean;
  session_name?: string;
};

type Signal = {
  symbol: string;
  status: 'A_PLUS_SETUP' | 'SCANNING' | 'WAITING_FOR_DATA';
  message?: string;
  action?: 'BUY' | 'SELL';
  session?: string;
  entry?: number;
  sl?: number;
  tp?: number;
  rr?: string;
  confluence_score: number;
  checklist: Checklist;
};

type RiskStatus = {
  state: string;
  max_open_positions: number;
  max_trades_per_day: number;
  max_daily_loss_percent: number;
  duplicate_symbol_protection: boolean;
  metrics?: {
    starting_balance: number;
    balance: number;
    open_positions: number;
    trades_today: number;
    realized_today: number;
  };
};

type MarketStatus = {
  symbol: string;
  source: string;
  last_price?: number | null;
  bid?: number | null;
  ask?: number | null;
  spread?: number | null;
  spread_points?: number | null;
  volatility_percent?: number | null;
  volatility_state?: 'LOW' | 'NORMAL' | 'ELEVATED' | 'UNAVAILABLE' | string;
};

type PositionSizePreview = {
  symbol: string;
  action: 'BUY' | 'SELL';
  risk_percent: number;
  balance: number;
  risk_amount: number;
  entry: number;
  sl: number;
  stop_distance: number;
  stop_pips?: number | null;
  lots: number;
  estimated_margin?: number | null;
  basis: string;
};

type RuntimeState = {
  execution_mode: 'PAPER' | 'LIVE';
  market_data_source: string;
  market_status?: MarketStatus;
  max_risk_percent?: number;
  active_session: string;
  broker: { connected: boolean; provider: string; reason?: string | null };
  capabilities: {
    paper_execution: boolean;
    live_execution: boolean;
    auto_execution: boolean;
    news_guard: boolean;
    position_ledger?: boolean;
    risk_guard?: boolean;
  };
  news_guard: { configured: boolean; active: boolean; provider?: string | null; message?: string };
  risk_guard?: RiskStatus;
};

type Position = {
  id: string;
  symbol: string;
  action: 'BUY' | 'SELL';
  lots: number;
  entry_price: number;
  mark_price?: number | null;
  sl: number;
  tp: number;
  risk_percent: number;
  status: string;
  unrealized_pnl: number;
  opened_at: string;
};

type Order = {
  id: string;
  symbol: string;
  action: 'BUY' | 'SELL';
  lots: number;
  entry_price: number;
  sl: number;
  tp: number;
  status: string;
  created_at: string;
};

type Portfolio = {
  account: {
    starting_balance: number;
    balance: number;
    equity: number;
    open_positions: number;
    trades_today: number;
    realized_today: number;
    unrealized_pnl: number;
  };
  positions: Position[];
  recent_orders: Order[];
  risk_guard?: RiskStatus;
};

type MarketItem = {
  symbol: string;
  price: number;
  change: number;
  change_percent: number;
  source: string;
  sparkline: number[];
};

const apiBase = process.env.NEXT_PUBLIC_AURA_API_URL || 'http://localhost:8000';
const wsBase = apiBase.replace(/^http/, 'ws');
const WATCHLIST = ['EURUSD', 'XAUUSD', 'GBPUSD', 'USDJPY', 'BTCUSD', 'ETHUSD'];

const EMPTY_SIGNAL: Signal = {
  symbol: 'EURUSD',
  status: 'WAITING_FOR_DATA',
  message: 'Connecting to AURA market intelligence…',
  confluence_score: 0,
  checklist: { sweep: false, displacement: false, fvg_midpoint: false, killzone_active: false },
};

const EMPTY_RUNTIME: RuntimeState = {
  execution_mode: 'PAPER',
  market_data_source: '—',
  max_risk_percent: 1,
  active_session: '—',
  broker: { connected: false, provider: 'Simulation Feed' },
  capabilities: { paper_execution: true, live_execution: false, auto_execution: false, news_guard: false },
  news_guard: { configured: false, active: false },
};

const EMPTY_PORTFOLIO: Portfolio = {
  account: {
    starting_balance: 10000,
    balance: 10000,
    equity: 10000,
    open_positions: 0,
    trades_today: 0,
    realized_today: 0,
    unrealized_pnl: 0,
  },
  positions: [],
  recent_orders: [],
};

function formatPrice(value?: number | null, symbol = '') {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  if (symbol.includes('JPY')) return value.toFixed(3);
  if (value >= 1000) return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (value >= 20) return value.toFixed(2);
  return value.toFixed(5);
}

function formatMoney(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '$—';
  const sign = value < 0 ? '-' : '';
  return `${sign}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatPct(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function assetClassLabel(symbol: string, t: any) {
  if (['EURUSD', 'GBPUSD', 'USDJPY'].includes(symbol)) return t.forex;
  if (symbol === 'XAUUSD') return t.metals;
  if (['BTCUSD', 'ETHUSD'].includes(symbol)) return t.crypto;
  if (['NAS100', 'SP500'].includes(symbol)) return t.indices;
  if (symbol === 'USOIL') return t.commodities;
  return t.markets;
}

function utcClock() {
  return new Date().toLocaleTimeString([], { hour12: false, timeZone: 'UTC' });
}

function symbolGlyph(symbol: string) {
  const glyphs: Record<string, string> = {
    EURUSD: '€', GBPUSD: '£', USDJPY: '¥', XAUUSD: 'Au',
    BTCUSD: '₿', ETHUSD: 'Ξ', NAS100: 'NQ', USOIL: 'WTI', SP500: 'S&P',
  };
  return glyphs[symbol] || symbol.slice(0, 2);
}

function pnlClass(value: number) {
  if (value > 0) return 'text-[#2ae9bd]';
  if (value < 0) return 'text-[#ff536d]';
  return 'text-slate-400';
}

function LogoMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`flex items-center ${compact ? 'gap-2' : 'gap-3'}`}>
      <svg className="aura-logo-glow h-7 w-7 shrink-0" viewBox="0 0 32 32" fill="none" aria-hidden="true">
        <path d="M6.5 25.5 14.3 5.8c.6-1.5 2.7-1.6 3.4-.1l8 19.8" stroke="#168CFF" strokeWidth="3.2" strokeLinecap="round" />
        <path d="m10.1 20.4 5.8-8.2 6 8.3" stroke="#37E9C0" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {!compact && <span className="text-[20px] font-semibold tracking-[0.12em] text-white">AURA</span>}
    </div>
  );
}

function TinySparkline({ values, positive }: { values: number[]; positive: boolean }) {
  const points = useMemo(() => {
    if (!values.length) return '';
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    return values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * 100},${28 - ((v - min) / span) * 22}`).join(' ');
  }, [values]);
  return (
    <svg viewBox="0 0 100 32" className="h-8 w-24 overflow-visible" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points} fill="none" stroke={positive ? '#2ae9bd' : '#ff536d'} strokeWidth="1.7" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function TerminalChart({ candles, signal, source, streamState, t }: { candles: Candle[]; signal: Signal; source: string; streamState: StreamState; t: any }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const priceLinesRef = useRef<any[]>([]);
  const last = candles[candles.length - 1];
  const hasSweep = !!signal.checklist.sweep;
  const hasFvg = !!signal.checklist.fvg_midpoint;
  const hasDisplacement = !!signal.checklist.displacement;
  const hasKillzone = !!signal.checklist.killzone_active;
  const hasValidatedStructure = signal.status === 'A_PLUS_SETUP' && hasSweep && hasFvg && hasDisplacement;

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      width: ref.current.clientWidth,
      height: ref.current.clientHeight,
      layout: { background: { color: 'transparent' }, textColor: '#70859b', fontSize: 10 },
      grid: { vertLines: { color: 'rgba(68,108,143,.12)' }, horzLines: { color: 'rgba(68,108,143,.12)' } },
      crosshair: {
        vertLine: { color: 'rgba(117,151,182,.33)', labelBackgroundColor: '#0a1723' },
        horzLine: { color: 'rgba(117,151,182,.33)', labelBackgroundColor: '#0a1723' },
      },
      rightPriceScale: { borderColor: 'rgba(73,113,148,.19)', scaleMargins: { top: 0.08, bottom: 0.24 } },
      timeScale: { borderColor: 'rgba(73,113,148,.19)', timeVisible: true, secondsVisible: false, rightOffset: 3 },
      handleScroll: true,
      handleScale: true,
    });
    const series = chart.addCandlestickSeries({
      upColor: '#16d9b0', downColor: '#ef4966', borderUpColor: '#16d9b0', borderDownColor: '#ef4966', wickUpColor: '#1ce2b9', wickDownColor: '#ff5b75',
    });
    chartRef.current = chart;
    seriesRef.current = series;
    const ro = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth, height: ref.current.clientHeight });
    });
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || !candles.length) return;
    seriesRef.current.setData(candles as any);
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    for (const line of priceLinesRef.current) {
      try { series.removePriceLine(line); } catch { /* no-op */ }
    }
    priceLinesRef.current = [];
    if (signal.status !== 'A_PLUS_SETUP' || !signal.entry || !signal.sl || !signal.tp) return;
    priceLinesRef.current = [
      series.createPriceLine({ price: signal.entry, color: '#2e93ff', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'ENTRY' }),
      series.createPriceLine({ price: signal.sl, color: '#ff536d', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SL' }),
      series.createPriceLine({ price: signal.tp, color: '#2ae9bd', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TP' }),
    ];
  }, [signal.status, signal.entry, signal.sl, signal.tp]);

  const osc = useMemo(() => {
    if (candles.length < 2) return [] as number[];
    return candles.slice(-54).map((c, i, a) => i === 0 ? 0 : (c.close - a[i - 1].close));
  }, [candles]);
  const oscMax = Math.max(...osc.map(v => Math.abs(v)), 0.00001);
  const oscPoints = osc.map((v, i) => `${(i / Math.max(osc.length - 1, 1)) * 100},${50 - (v / oscMax) * 34}`).join(' ');

  return (
    <div className="relative h-full min-h-[330px] overflow-hidden bg-[#03101a]">
      <div className="absolute inset-0 aura-grid-bg" />
      <div ref={ref} className="absolute inset-0" />

      <div className="pointer-events-none absolute left-2 top-2 z-20 flex max-w-[calc(100%_-_16px)] items-center gap-2 overflow-hidden text-[10px] md:left-11 md:top-3">
        <span className={`flex shrink-0 items-center gap-1.5 ${streamState === 'connected' ? 'text-[#2ae9bd]' : streamState === 'reconnecting' ? 'text-[#ffb14a]' : 'text-[#ff536d]'}`}><span className={`h-1.5 w-1.5 rounded-full ${streamState === 'connected' ? 'aura-live-dot bg-[#2ae9bd]' : streamState === 'reconnecting' ? 'bg-[#ffb14a]' : 'bg-[#ff536d]'}`} />{streamState === 'connected' ? (source === 'MT5' ? t.connected : t.simulation) : streamState === 'reconnecting' ? t.reconnecting : t.offline}</span>
        <span className="text-[#466079]">•</span><span className="shrink-0 text-[#8ca0b4]">{assetClassLabel(signal.symbol, t)}</span><span className="text-[#466079]">•</span><span className="truncate text-[#8ca0b4]">{source}</span>
        {last && <span className="hidden force-ltr text-[#28dab6] lg:inline">O {formatPrice(last.open, signal.symbol)} &nbsp; H {formatPrice(last.high, signal.symbol)} &nbsp; L {formatPrice(last.low, signal.symbol)} &nbsp; C {formatPrice(last.close, signal.symbol)}</span>}
      </div>

      {hasSweep && <div className="pointer-events-none absolute left-[14%] top-[18%] z-10 w-[34%]">
        <span className="mb-1.5 block text-[10px] text-[#c7d6e3]">{t.liquiditySweep}</span>
        <div className="aura-zone h-7" />
      </div>}
      {hasFvg && <div className="pointer-events-none absolute left-[6%] top-[42%] z-10 w-[16%]">
        <div className="aura-zone h-5"><span className="absolute right-1 top-1 text-[8px] text-[#aec4d9] rtl:left-1 rtl:right-auto">{t.fvg}</span></div>
      </div>}
      {hasValidatedStructure && <div className="pointer-events-none absolute left-[39%] top-[56%] z-10 w-[37%]">
        <div className="aura-zone h-8"><span className="absolute left-2 top-2 text-[9px] text-[#d2ddec] rtl:left-auto rtl:right-2">{t.demandZone}</span></div>
      </div>}
      {hasDisplacement && <div className="pointer-events-none absolute left-[58%] top-[39%] z-10 flex items-center gap-2 text-[9px] text-[#c6d6e5]">
        <span>{t.breakOfStructure}</span><span className="h-px w-11 bg-[#9ac8ee]/70" />
      </div>}
      {hasKillzone && <div className="pointer-events-none absolute bottom-[21%] right-[14%] top-0 z-[5] w-[16%] aura-killzone rtl:left-[14%] rtl:right-auto">
        <div className="mt-8 text-center text-[9px] text-[#d5cef9]">{t.killzone} ({signal.checklist.session_name || signal.session || '—'})</div>
      </div>}

      <div className="pointer-events-none absolute bottom-[3px] left-0 right-0 z-10 h-[21%] border-t border-[#173047]/70 bg-[#03101a]/88 px-4 pt-2">
        <svg className="h-full w-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <line x1="0" y1="50" x2="100" y2="50" stroke="rgba(84,118,147,.22)" strokeWidth="0.5" />
          {osc.length > 1 && (
            <>
              <polyline points={oscPoints} fill="none" stroke="#2e93ff" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
              <polyline points={oscPoints.split(' ').map((p, i) => {
                const [x, y] = p.split(',').map(Number); const yy = 50 + (y - 50) * .55 + Math.sin(i / 4) * 7; return `${x},${yy}`;
              }).join(' ')} fill="none" stroke="#f59a3b" strokeWidth="1" vectorEffect="non-scaling-stroke" opacity=".85" />
            </>
          )}
        </svg>
      </div>

      {!candles.length && <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center">
        <div className="rounded-lg border border-[#17344e] bg-[#06131f]/92 px-4 py-3 text-center shadow-2xl backdrop-blur-sm">
          <div className={`mx-auto mb-2 h-2 w-2 rounded-full ${streamState === 'offline' ? 'bg-[#ff536d]' : 'aura-live-dot bg-[#2ae9bd]'}`} />
          <div className="text-[10px] font-medium text-[#d8e5ef]">{streamState === 'offline' ? t.marketDataUnavailable : t.marketLoading}</div>
          <div className="mt-1 text-[8px] text-[#60768b]">{streamState === 'reconnecting' ? t.reconnecting : source}</div>
        </div>
      </div>}

      <div className="absolute bottom-[22%] left-2 z-20 hidden flex-col gap-2 md:flex rtl:left-auto rtl:right-2">
        {[Crosshair, LineChart, Target, SlidersHorizontal, Layers3, Gauge, Search].map((Icon, i) => (
          <button key={i} className="flex h-7 w-7 items-center justify-center rounded text-[#7790a8] hover:bg-[#0b2134] hover:text-white" aria-label={`${t.chartTool} ${i + 1}`}>
            <Icon className="h-3.5 w-3.5" />
          </button>
        ))}
      </div>
    </div>
  );
}

function Sidebar({ view, setView, lang, setLang, t }: { view: View; setView: (view: View) => void; lang: Language; setLang: (lang: Language) => void; t: any }) {
  const nav = [
    [t.terminal, CandlestickChart, 'terminal'],
    [t.markets, BarChart3, 'markets'],
    [t.signals, Activity, 'signals'],
    [t.autoTrade, Bot, 'auto-trade'],
    [t.positions, WalletCards, 'positions'],
    [t.orders, ListOrdered, 'orders'],
    [t.performance, TrendingUp, 'performance'],
    [t.backtesting, LineChart, 'backtesting'],
    [t.newsGuard, ShieldCheck, 'news-guard'],
    [t.analytics, Gauge, 'analytics'],
    [t.calendar, CalendarDays, 'calendar'],
  ] as const;
  return (
    <aside className="aura-sidebar-bg hidden h-full w-[196px] shrink-0 border-r border-[#153047]/65 xl:flex xl:flex-col rtl:border-l rtl:border-r-0">
      <div className="flex h-[64px] items-center justify-between border-b border-[#153047]/55 px-5">
        <LogoMark />
        <PanelLeftClose className="h-4 w-4 text-[#667e95]" />
      </div>
      <nav className="aura-thin-scroll flex-1 overflow-y-auto px-3 py-4">
        <div className="space-y-1">
          {nav.map(([label, Icon, target], index) => {
            const active = target === view;
            return (
              <button key={`${label}-${index}`} onClick={() => setView(target)} className={`aura-nav-item ${active ? 'is-active' : ''}`}>
                <Icon className="h-[15px] w-[15px] shrink-0" />
                <span className="truncate">{label}</span>
              </button>
            );
          })}
        </div>
      </nav>
      <div className="px-3 pb-3">
        <div className="aura-pro-card rounded-lg p-3">
          <div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-[#ffd77b]" /><span className="text-xs font-semibold text-white">{t.pro}</span></div>
          <div className="mt-1 text-[9px] text-[#b9c9da]">{t.proDesc}</div>
          <button className="mt-3 w-full rounded-md bg-gradient-to-r from-[#2178f5] to-[#8b4df8] py-2 text-[10px] font-semibold text-white shadow-lg shadow-indigo-950/20">{t.upgrade}</button>
        </div>
      </div>
      <div className="border-t border-[#153047]/60 p-3">
        <div className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-white/[.025]">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-[#d59f77] to-[#233b56] text-[10px] font-semibold text-white">AT</div>
          <div className="min-w-0 flex-1"><div className="truncate text-[11px] font-medium text-white">{t.trader}</div><div className="truncate text-[9px] text-[#60758b]">terminal@aura.trade</div></div>
          <ChevronDown className="h-3.5 w-3.5 text-[#647a91]" />
        </div>
        <button onClick={() => setLang(lang === 'en' ? 'fa' : 'en')} className="mt-1 flex w-full items-center justify-between rounded-lg px-2 py-2 text-[10px] text-[#72879b] hover:bg-white/[.025] hover:text-white">
          <span className="flex items-center gap-2"><Languages className="h-3.5 w-3.5" />{t.language}</span><span>{lang === 'en' ? 'FA' : 'EN'}</span>
        </button>
      </div>
    </aside>
  );
}

function TopBar({ runtime, portfolio, lang, setLang, t }: { runtime: RuntimeState; portfolio: Portfolio; lang: Language; setLang: (l: Language) => void; t: any }) {
  const pnl = portfolio.account.unrealized_pnl;
  const pnlPct = portfolio.account.balance ? pnl / portfolio.account.balance * 100 : 0;
  return (
    <header className="flex h-[48px] shrink-0 items-center gap-3 border-b border-[#153047]/65 bg-[#03101a]/95 px-3 lg:px-4">
      <div className="xl:hidden"><LogoMark compact /></div>
      <div className="relative hidden w-[235px] sm:block">
        <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#688099] rtl:left-auto rtl:right-3" />
        <input className="h-8 w-full rounded-md border border-[#17344e] bg-[#06131f] px-9 text-[10px] text-white placeholder:text-[#60768d]" placeholder={t.search} />
        <span className="absolute right-2 top-1/2 -translate-y-1/2 rounded border border-[#24435d] px-1.5 py-0.5 text-[8px] text-[#71879b] rtl:left-2 rtl:right-auto">⌘ K</span>
      </div>
      <div className="ml-auto flex h-full items-center gap-2 rtl:ml-0 rtl:mr-auto">
        <div className={`hidden items-center gap-1.5 rounded-md px-2 py-1 text-[9px] font-semibold sm:flex ${runtime.execution_mode === 'LIVE' ? 'bg-[#0c553f]/45 text-[#2ae9bd]' : 'bg-[#16395d]/50 text-[#75bdff]'}`}>
          <span className="aura-live-dot h-1.5 w-1.5 rounded-full bg-current" />{runtime.execution_mode === 'LIVE' ? t.live : t.paper}<ChevronDown className="h-3 w-3" />
        </div>
        <div className="hidden h-8 items-center gap-2 rounded-md border border-[#17344e] bg-[#071522] px-3 text-[9px] text-[#d8e4ef] md:flex">
          <span>{runtime.execution_mode === 'LIVE' ? t.liveAccount : t.paperAccount}</span><span className="aura-mono text-[#7b8fa4]">(AURA-001)</span><ChevronDown className="h-3 w-3 text-[#657c91]" />
        </div>
        <div className="hidden h-full items-center lg:flex">
          <div className="border-l border-[#163047]/70 px-3 rtl:border-l-0 rtl:border-r"><div className="text-[8px] text-[#60758a]">{t.balance}</div><div className="aura-mono text-[10px] font-semibold text-white">{formatMoney(portfolio.account.balance)}</div></div>
          <div className="border-l border-[#163047]/70 px-3 rtl:border-l-0 rtl:border-r"><div className="text-[8px] text-[#60758a]">{t.equity}</div><div className="aura-mono text-[10px] font-semibold text-white">{formatMoney(portfolio.account.equity)}</div></div>
          <div className="border-l border-[#163047]/70 px-3 rtl:border-l-0 rtl:border-r"><div className="text-[8px] text-[#60758a]">{t.openPnl}</div><div className={`aura-mono text-[10px] font-semibold ${pnlClass(pnl)}`}>{formatMoney(pnl)} ({formatPct(pnlPct)})</div></div>
        </div>
        <button onClick={() => setLang(lang === 'en' ? 'fa' : 'en')} className="flex h-8 w-8 items-center justify-center rounded-md border border-[#17344e] text-[#8ca1b5] hover:text-white xl:hidden" aria-label="Language"><Globe2 className="h-3.5 w-3.5" /></button>
        <button className="relative flex h-8 w-8 items-center justify-center rounded-md text-[#879caf] hover:bg-[#0a1c2c] hover:text-white" aria-label="Notifications"><Bell className="h-4 w-4" /><span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-[#ff3b66]" /></button>
      </div>
    </header>
  );
}

function WatchlistStrip({ items, selectedSymbol, setSelectedSymbol }: { items: MarketItem[]; selectedSymbol: string; setSelectedSymbol: (s: string) => void }) {
  const map = new Map(items.map(item => [item.symbol, item]));
  return (
    <div className="aura-thin-scroll hidden h-[52px] shrink-0 items-center gap-2 overflow-x-auto border-b border-[#153047]/60 bg-[#020c15]/94 px-3 md:flex">
      {WATCHLIST.map(symbol => {
        const item = map.get(symbol);
        const positive = (item?.change_percent || 0) >= 0;
        return (
          <button key={symbol} onClick={() => setSelectedSymbol(symbol)} className={`aura-symbol-card ${selectedSymbol === symbol ? 'is-active' : ''}`}>
            <div className="flex items-center justify-between gap-3"><span className="aura-mono text-[10px] font-semibold text-white">{symbol}</span><span className={`aura-mono text-[9px] ${positive ? 'text-[#2ae9bd]' : 'text-[#ff536d]'}`}>{formatPct(item?.change_percent || 0)}</span></div>
            <div className="mt-0.5 text-left aura-mono text-[9px] text-[#a8b7c5] rtl:text-right">{formatPrice(item?.price, symbol)}</div>
          </button>
        );
      })}
      <button className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[#17344e] bg-[#071522] text-[#8397aa]"><Plus className="h-3.5 w-3.5" /></button>
    </div>
  );
}

function ChartHeader({ symbol, t }: { symbol: string; t: any }) {
  return (
    <div className="flex h-[43px] shrink-0 items-center border-b border-[#173047]/70 bg-[#04111c]">
      <div className="flex h-full min-w-[145px] items-center gap-3 border-r border-[#173047]/70 px-3 rtl:border-l rtl:border-r-0">
        <div className="flex h-7 min-w-7 items-center justify-center rounded-full border border-[#2b74b4] bg-[#123660] px-1 text-[9px] font-bold text-[#7ec0ff]">{symbolGlyph(symbol)}</div>
        <div><div className="aura-mono text-[12px] font-semibold text-white">{symbol}</div><div className="text-[8px] text-[#6f8498]">{symbol === 'EURUSD' ? 'Euro / U.S. Dollar' : `AURA · ${assetClassLabel(symbol, t)}`}</div></div>
      </div>
      <div className="aura-thin-scroll flex min-w-0 flex-1 items-center gap-1 overflow-x-auto px-2 text-[9px] text-[#8499ad]">
        {['1m','5m','15m','1h','4h','D'].map(tf => <button key={tf} className={`rounded px-2 py-1.5 ${tf === '15m' ? 'bg-[#14304a] text-white' : 'hover:bg-[#0c2133] hover:text-white'}`}>{tf}</button>)}
        <ChevronDown className="h-3 w-3" />
        <span className="mx-1 h-5 w-px bg-[#163047]" />
        <button className="flex items-center gap-1 rounded px-2 py-1.5 hover:bg-[#0c2133]"><Activity className="h-3 w-3" />{t.indicators}</button>
        <button className="hidden items-center gap-1 rounded px-2 py-1.5 hover:bg-[#0c2133] lg:flex"><Layers3 className="h-3 w-3" />{t.templates}</button>
        <button className="hidden items-center gap-1 rounded px-2 py-1.5 hover:bg-[#0c2133] lg:flex"><RefreshCcw className="h-3 w-3" />{t.replay}</button>
      </div>
      <div className="flex h-full items-center gap-1 border-l border-[#173047]/70 px-2 rtl:border-l-0 rtl:border-r">
        {[Crosshair, SlidersHorizontal, MoreHorizontal].map((Icon, i) => <button key={i} className="flex h-7 w-7 items-center justify-center rounded text-[#7f94a8] hover:bg-[#0c2133] hover:text-white"><Icon className="h-3.5 w-3.5" /></button>)}
      </div>
    </div>
  );
}

function SignalCard({ signal, t }: { signal: Signal; t: any }) {
  const ready = signal.status === 'A_PLUS_SETUP';
  const action = signal.action || 'BUY';
  const sideColor = action === 'BUY' ? 'text-[#2ae9bd]' : 'text-[#ff536d]';
  const chip = ready ? t.setup : signal.status === 'SCANNING' ? t.scanning : t.waiting;
  return (
    <section className="aura-panel rounded-lg p-3.5">
      <div className="flex items-center justify-between"><h3 className="text-[12px] font-semibold text-white">{t.auraSignal}</h3><span className={`rounded px-2 py-1 text-[8px] font-semibold ${ready ? 'bg-[#0b5942]/55 text-[#43ebc2]' : 'bg-[#203349] text-[#8fa7bc]'}`}>{chip}</span></div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div className="flex items-end gap-3"><div className={`text-[28px] font-bold leading-none ${ready ? sideColor : 'text-[#667c91]'}`}>{ready ? action : '—'}</div><div><div className="aura-mono text-[12px] font-semibold text-white">{signal.symbol}</div><div className="text-[9px] text-[#8598aa]">{t.confluenceScore}</div></div></div>
        <div className="flex items-end gap-1.5"><span className={`aura-mono text-[24px] leading-none ${ready ? 'text-[#2ae9bd]' : 'text-[#73879b]'}`}>{Math.round(signal.confluence_score || 0)}</span><span className="pb-0.5 text-[10px] text-[#8395a8]">/100</span><div className="mb-1 ml-1 flex gap-1 rtl:ml-0 rtl:mr-1">{[1,2,3,4].map(i => <span key={i} className={`h-4 w-2.5 ${signal.confluence_score >= i*20 ? 'bg-[#2ae9bd]/65' : 'bg-[#183047]'}`} />)}</div></div>
      </div>
      <div className="mt-3 grid grid-cols-3 border-y border-[#173047]/70 py-3">
        <div><div className="text-[8px] text-[#73879b]">{t.entry}</div><div className="mt-1 aura-mono text-[12px] text-white">{formatPrice(signal.entry, signal.symbol)}</div></div>
        <div className="border-x border-[#173047]/70 px-3"><div className="text-[8px] text-[#73879b]">{t.stopLoss}</div><div className="mt-1 aura-mono text-[12px] text-[#ff536d]">{formatPrice(signal.sl, signal.symbol)}</div></div>
        <div className="pl-3 rtl:pl-0 rtl:pr-3"><div className="text-[8px] text-[#73879b]">{t.takeProfit}</div><div className="mt-1 aura-mono text-[12px] text-[#2ae9bd]">{formatPrice(signal.tp, signal.symbol)}</div></div>
      </div>
      <div className="mt-2 flex items-center gap-2 text-[9px]"><span className="text-[#70869b]">{t.riskReward}</span><span className="aura-mono text-[#b8cadb]">{signal.rr || '—'}</span></div>
      <div className="mt-3 grid grid-cols-2 gap-1.5 xl:grid-cols-4">
        {[[t.liquiditySweep, signal.checklist.sweep],[t.fvg, signal.checklist.fvg_midpoint],[t.displacement, signal.checklist.displacement],[t.londonKillzone, signal.checklist.killzone_active]].map(([label, active]) => <span key={String(label)} className={`aura-chip !px-2 !text-[8px] ${active ? '!border-[#226a5a] !bg-[#0b4338] !text-[#76ead0]' : 'opacity-55'}`}>{String(label)}</span>)}
      </div>
    </section>
  );
}

function ExecuteCard({ signal, portfolio, runtime, sizing, riskPercent, setRiskPercent, operatorKey, setOperatorKey, executing, onExecute, t }: { signal: Signal; portfolio: Portfolio; runtime: RuntimeState; sizing: PositionSizePreview | null; riskPercent: number; setRiskPercent: (v: number) => void; operatorKey: string; setOperatorKey: (v: string) => void; executing: boolean; onExecute: () => void; t: any }) {
  const ready = signal.status === 'A_PLUS_SETUP' && !!signal.action && !!signal.entry && !!signal.sl && !!signal.tp;
  const canExecute = ready && !!sizing && (runtime.capabilities.paper_execution || (runtime.capabilities.live_execution && operatorKey.trim().length > 0));
  const lot = sizing?.lots || 0;
  const label = signal.action === 'SELL' ? t.executeSell : signal.action === 'BUY' ? t.executeBuy : t.executeOrder;
  return (
    <section className="aura-panel rounded-lg p-3.5">
      <h3 className="text-[12px] font-semibold text-white">{t.executeTrade}</h3>
      <div className="mt-3 grid grid-cols-3 overflow-hidden rounded-md border border-[#17344e] bg-[#05111c] text-[9px]"><button className="bg-[#1e5a90] py-2 text-white">{t.market}</button><button className="py-2 text-[#8296aa]">{t.pending}</button><button className="py-2 text-[#8296aa]">{t.slTp}</button></div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <label><span className="mb-1.5 block text-[8px] text-[#8195a8]">{t.riskPercent}</span><input className="aura-field force-ltr" type="number" min="0.1" max={runtime.max_risk_percent || 1} step="0.1" value={riskPercent} onChange={e => setRiskPercent(Math.min(runtime.max_risk_percent || 1, Math.max(.1, Number(e.target.value) || .1)))} /></label>
        <label><span className="mb-1.5 block text-[8px] text-[#8195a8]">{t.lotSizeAuto}</span><div className="aura-field flex items-center force-ltr">{lot ? lot.toFixed(2) : '—'}</div></label>
      </div>
      <div className="mt-2 flex gap-1.5">{[.5,1,2].filter(v => v <= (runtime.max_risk_percent || 1)).map(v => <button key={v} onClick={() => setRiskPercent(v)} className={`rounded px-2 py-1 text-[8px] ${riskPercent === v ? 'bg-[#1d5587] text-white' : 'bg-[#10243a] text-[#8599ac]'}`}>{v}%</button>)}</div>
      {runtime.execution_mode === 'LIVE' && <label className="mt-3 block"><span className="mb-1.5 flex items-center justify-between text-[8px] text-[#8195a8]"><span>{t.operatorAuthorization}</span><span className="text-[#5f778c]">{t.idempotencyProtected}</span></span><input className="aura-field force-ltr" type="password" autoComplete="off" value={operatorKey} onChange={e => setOperatorKey(e.target.value)} placeholder={t.operatorKeyPlaceholder} /></label>}
      <button onClick={onExecute} disabled={!canExecute || executing} className="aura-execute mt-3 flex h-10 w-full items-center justify-center gap-2 rounded-md text-[11px] font-bold transition">{executing ? <Zap className="h-3.5 w-3.5 animate-pulse" /> : <Play className="h-3.5 w-3.5 fill-current" />}{executing ? t.routing : label}<ChevronRight className="h-3.5 w-3.5 rtl:rotate-180" /></button>
      {!canExecute && <div className="mt-2 text-center text-[8px] leading-4 text-[#586f84]">{t.riskBlocked}</div>}
    </section>
  );
}

function StatusColumn({ runtime, portfolio, signal, sizing, riskPercent, t }: { runtime: RuntimeState; portfolio: Portfolio; signal: Signal; sizing: PositionSizePreview | null; riskPercent: number; t: any }) {
  const market = runtime.market_status;
  const session = runtime.active_session || signal.checklist.session_name || '—';
  const volatilityState = market?.volatility_state || 'UNAVAILABLE';
  const volatilityClass = volatilityState === 'ELEVATED' ? 'text-[#ffb14a]' : volatilityState === 'UNAVAILABLE' ? 'text-[#71869b]' : 'text-[#2ae9bd]';
  return (
    <div className="hidden min-w-0 flex-col gap-2 xl:flex">
      <section className="aura-panel rounded-lg p-3.5">
        <div className="flex items-center justify-between"><h3 className="text-[12px] font-semibold text-white">{t.marketStatus}</h3><span className={`flex items-center gap-1 rounded px-2 py-1 text-[8px] font-semibold ${runtime.execution_mode === 'LIVE' ? 'bg-[#0c553f]/50 text-[#2ae9bd]' : 'bg-[#173a5f] text-[#78bfff]'}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{runtime.execution_mode === 'LIVE' ? t.live : t.paper}</span></div>
        <div className="mt-3 grid grid-cols-2 gap-y-4 text-[9px]"><div><div className="text-[#71869b]">{t.spread}</div><div className="mt-1 aura-mono text-[11px] text-white">{typeof market?.spread_points === 'number' ? `${market.spread_points.toFixed(1)} pt` : '—'}</div></div><div><div className="text-[#71869b]">{t.volatility}</div><div className={`mt-1 text-[11px] ${volatilityClass}`}>{volatilityState === 'UNAVAILABLE' ? '—' : `${volatilityState} · ${(market?.volatility_percent || 0).toFixed(3)}%`}</div></div><div><div className="text-[#71869b]">{t.session}</div><div className="mt-1 text-[11px] text-white">{session}</div></div><div><div className="text-[#71869b]">{t.killzoneActive}</div><div className="mt-1 text-[11px] text-white">{signal.checklist.killzone_active ? t.active : '—'}</div></div></div>
      </section>
      <section className="aura-panel rounded-lg p-3.5">
        <div className="flex items-center justify-between"><h3 className="text-[12px] font-semibold text-white">{t.newsGuard}</h3><span className={`flex items-center gap-1 rounded px-2 py-1 text-[8px] font-semibold ${runtime.news_guard.configured ? 'bg-[#0c553f]/50 text-[#2ae9bd]' : 'bg-[#3c2f1b] text-[#e6b866]'}`}><ShieldCheck className="h-3 w-3" />{runtime.news_guard.configured ? t.safe : t.notConfigured}</span></div>
        <p className="mt-3 min-h-[28px] text-[9px] leading-4 text-[#9aabba]">{runtime.news_guard.configured ? t.newsSafe : t.newsPending}</p>
        <button className="mt-2 w-full rounded-md border border-[#17344e] bg-[#071522] py-2 text-[9px] text-[#9aabba] hover:text-white">{t.viewCalendar}</button>
      </section>
      <section className="aura-panel rounded-lg p-3.5">
        <h3 className="text-[12px] font-semibold text-white">{t.positionSizing}</h3>
        <div className="mt-3 space-y-3 text-[9px]">
          <div className="flex items-center justify-between"><span className="text-[#7890a4]">{t.accountBalance}</span><span className="aura-mono text-white">{formatMoney(portfolio.account.balance)}</span></div>
          <div className="flex items-center justify-between"><span className="text-[#7890a4]">{t.riskAmount} ({riskPercent}%)</span><span className="aura-mono text-white">{formatMoney(sizing?.risk_amount)}</span></div>
          <div className="flex items-center justify-between"><span className="text-[#7890a4]">{t.stopDistance}</span><span className="aura-mono text-white">{typeof sizing?.stop_pips === 'number' ? `${sizing.stop_pips.toFixed(1)} pips` : typeof sizing?.stop_distance === 'number' ? formatPrice(sizing.stop_distance, signal.symbol) : '—'}</span></div>
          <div className="flex items-center justify-between"><span className="text-[#7890a4]">{t.lotSize}</span><span className="aura-mono text-white">{sizing?.lots ? sizing.lots.toFixed(2) : '—'}</span></div>
          <div className="flex items-center justify-between"><span className="text-[#7890a4]">{t.estMargin}</span><span className="aura-mono text-white">{typeof sizing?.estimated_margin === 'number' ? formatMoney(sizing.estimated_margin) : '—'}</span></div>
        </div>
      </section>
    </div>
  );
}

function PositionsPanel({ portfolio, onClose, t }: { portfolio: Portfolio; onClose: (id: string) => void; t: any }) {
  return (
    <section className="aura-panel min-h-[155px] overflow-hidden rounded-lg">
      <div className="aura-thin-scroll flex h-10 items-end gap-6 overflow-x-auto border-b border-[#173047]/70 px-3 text-[9px] text-[#8da1b4]">
        <button className="h-10 border-b-2 border-[#2ea7ff] px-1 text-white">{t.openPositions} ({portfolio.positions.length})</button><button className="h-10 px-1">{t.pendingOrders} (0)</button><button className="h-10 px-1">{t.history}</button><button className="h-10 px-1">{t.closedPositions}</button>
      </div>
      <div className="aura-thin-scroll overflow-x-auto">
        <table className="w-full min-w-[820px] border-collapse text-left text-[9px] rtl:text-right">
          <thead><tr className="border-b border-[#132b40] text-[#72879b]">{[t.symbol,t.type,t.lot,t.entry,t.current,t.stopLoss,t.takeProfit,t.pnlDollar,t.pnlPercent,t.actions].map(h => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
          <tbody>
            {portfolio.positions.length === 0 ? <tr><td colSpan={10} className="px-4 py-8 text-center text-[10px] text-[#5f7589]">{t.noPositions}</td></tr> : portfolio.positions.map(position => {
              const pct = position.entry_price && position.lots ? (position.unrealized_pnl / Math.max(portfolio.account.balance,1))*100 : 0;
              return <tr key={position.id} className="border-b border-[#10283c] text-[#d2dde7] hover:bg-[#081827]">
                <td className="aura-mono px-3 py-2 text-white">{position.symbol}</td><td className={`px-3 py-2 font-semibold ${position.action === 'BUY' ? 'text-[#2ae9bd]' : 'text-[#ff536d]'}`}>{position.action}</td><td className="aura-mono px-3 py-2">{position.lots.toFixed(2)}</td><td className="aura-mono px-3 py-2">{formatPrice(position.entry_price, position.symbol)}</td><td className="aura-mono px-3 py-2">{formatPrice(position.mark_price, position.symbol)}</td><td className="aura-mono px-3 py-2">{formatPrice(position.sl, position.symbol)}</td><td className="aura-mono px-3 py-2">{formatPrice(position.tp, position.symbol)}</td><td className={`aura-mono px-3 py-2 ${pnlClass(position.unrealized_pnl)}`}>{formatMoney(position.unrealized_pnl)}</td><td className={`aura-mono px-3 py-2 ${pnlClass(pct)}`}>{formatPct(pct)}</td><td className="px-3 py-2"><button onClick={() => onClose(position.id)} className="rounded border border-[#24435d] bg-[#102238] px-3 py-1 text-[8px] text-[#b8c9d7] hover:text-white">{t.close}</button></td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RecentSignals({ signal, portfolio, t }: { signal: Signal; portfolio: Portfolio; t: any }) {
  const rows = [
    ...(signal.status === 'A_PLUS_SETUP' ? [{ symbol: signal.symbol, action: signal.action || 'BUY', score: Math.round(signal.confluence_score), time: 'now' }] : []),
    ...portfolio.recent_orders.slice(0, 5).map(order => ({ symbol: order.symbol, action: order.action, score: 0, time: new Date(order.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) })),
  ].slice(0, 5);
  return (
    <aside className="aura-panel hidden min-w-0 rounded-lg p-3 lg:block">
      <div className="flex items-center justify-between"><h3 className="text-[11px] font-semibold text-white">{t.recentSignals}</h3><button className="rounded bg-[#10243a] px-2 py-1 text-[8px] text-[#94a8ba]">{t.viewAll}</button></div>
      <div className="mt-2 space-y-2.5">{rows.length ? rows.map((row, i) => <div key={`${row.symbol}-${i}`} className="grid grid-cols-[1fr_auto_auto] items-center gap-2 text-[9px]"><div className="flex items-center gap-2"><span className="flex h-4 w-4 items-center justify-center rounded-full bg-[#123152] text-[7px] text-[#84c2ff]">◉</span><span className="aura-mono text-[#d7e2ec]">{row.symbol}</span></div><span className={`rounded px-1.5 py-0.5 text-[7px] font-semibold ${row.action === 'BUY' ? 'bg-[#0b493a] text-[#2ae9bd]' : 'bg-[#4b1e2a] text-[#ff6d83]'}`}>{row.action}</span><div className="text-right"><div className="aura-mono text-[#b8c8d7]">{row.score || 'EXEC'}</div><div className="text-[7px] text-[#60768b]">{row.time}</div></div></div>) : <div className="py-8 text-center text-[9px] text-[#60768b]">{t.noSetup}</div>}</div>
    </aside>
  );
}

function MobileTerminalView({ candles, signal, runtime, portfolio, sizing, riskPercent, setRiskPercent, operatorKey, setOperatorKey, executing, onExecute, streamState, t }: { candles: Candle[]; signal: Signal; runtime: RuntimeState; portfolio: Portfolio; sizing: PositionSizePreview | null; riskPercent: number; setRiskPercent: (v: number) => void; operatorKey: string; setOperatorKey: (v: string) => void; executing: boolean; onExecute: () => void; streamState: StreamState; t: any }) {
  const ready = signal.status === 'A_PLUS_SETUP' && !!signal.action;
  return (
    <main className="aura-thin-scroll min-h-0 flex-1 overflow-y-auto bg-[#020b14] px-3 pb-24 pt-3 md:hidden">
      <section className="aura-panel overflow-hidden rounded-xl">
        <div className="flex items-center justify-between border-b border-[#173047] px-3 py-3">
          <div><div className="aura-mono text-[12px] font-semibold text-white">{signal.symbol}</div><div className="mt-0.5 text-[8px] text-[#6f8498]">{runtime.market_data_source === 'MT5' ? t.connected : t.simulation}</div></div>
          <span className={`rounded px-2 py-1 text-[8px] font-semibold ${ready ? 'bg-[#0b5942]/55 text-[#43ebc2]' : 'bg-[#17334e] text-[#86a2ba]'}`}>{ready ? t.setup : signal.status === 'SCANNING' ? t.scanning : t.waiting}</span>
        </div>
        <div className="px-3 pb-3 pt-3">
          <div className="flex items-end justify-between">
            <div className={`text-[27px] font-bold leading-none ${signal.action === 'SELL' ? 'text-[#ff536d]' : ready ? 'text-[#2ae9bd]' : 'text-[#60768b]'}`}>{ready ? signal.action : '—'}</div>
            <div className="text-right rtl:text-left"><div className="text-[8px] text-[#758a9d]">{t.confluenceScore}</div><div className="aura-mono text-[17px] text-[#2ae9bd]">{Math.round(signal.confluence_score || 0)}<span className="text-[9px] text-[#71869b]">/100</span></div></div>
          </div>
          <div className="mt-3 grid grid-cols-3 border-y border-[#173047] py-3">
            <div><div className="text-[8px] text-[#70869a]">{t.entry}</div><div className="mt-1 aura-mono text-[11px] text-white">{formatPrice(signal.entry, signal.symbol)}</div></div>
            <div className="border-x border-[#173047] px-2"><div className="text-[8px] text-[#70869a]">{t.stopLoss}</div><div className="mt-1 aura-mono text-[11px] text-[#ff536d]">{formatPrice(signal.sl, signal.symbol)}</div></div>
            <div className="pl-2 rtl:pl-0 rtl:pr-2"><div className="text-[8px] text-[#70869a]">{t.takeProfit}</div><div className="mt-1 aura-mono text-[11px] text-[#2ae9bd]">{formatPrice(signal.tp, signal.symbol)}</div></div>
          </div>
        </div>
        <div className="h-[285px] border-t border-[#173047]"><TerminalChart candles={candles} signal={signal} source={runtime.market_data_source} streamState={streamState} t={t} /></div>
        <div className="aura-thin-scroll flex items-center gap-2 overflow-x-auto border-t border-[#173047] px-3 py-2 text-[9px] text-[#7f94a8]">{['5m','15m','1h','4h','D'].map(tf => <button key={tf} className={`rounded px-3 py-1.5 ${tf === '15m' ? 'bg-[#153958] text-white' : 'bg-[#071522]'}`}>{tf}</button>)}</div>
        <div className="p-3"><ExecuteCard signal={signal} portfolio={portfolio} runtime={runtime} sizing={sizing} riskPercent={riskPercent} setRiskPercent={setRiskPercent} operatorKey={operatorKey} setOperatorKey={setOperatorKey} executing={executing} onExecute={onExecute} t={t} /></div>
      </section>
    </main>
  );
}

function MarketsView({ items, selectedSymbol, setSelectedSymbol, t }: { items: MarketItem[]; selectedSymbol: string; setSelectedSymbol: (s: string) => void; t: any }) {
  const [filter, setFilter] = useState('all');
  const categories: Record<string, string[]> = { forex: ['EURUSD','GBPUSD','USDJPY'], metals: ['XAUUSD'], crypto: ['BTCUSD','ETHUSD'], indices: ['NAS100','SP500'], commodities: ['USOIL'] };
  const visible = filter === 'all' ? items : items.filter(item => categories[filter]?.includes(item.symbol));
  return (
    <main className="aura-thin-scroll min-h-0 flex-1 overflow-y-auto bg-[#020b14] p-4 lg:p-5">
      <div className="mx-auto max-w-[1100px]">
        <h1 className="text-[18px] font-semibold text-white">{t.marketsTitle}</h1>
        <div className="mt-4 flex flex-wrap gap-2">{[['all',t.all],['forex',t.forex],['metals',t.metals],['indices',t.indices],['crypto',t.crypto],['commodities',t.commodities]].map(([key,label]) => <button key={key} onClick={() => setFilter(String(key))} className={`rounded-md border px-3 py-1.5 text-[9px] ${filter === key ? 'border-[#246ba4] bg-[#12375a] text-white' : 'border-[#17344e] bg-[#071522] text-[#8da1b4]'}`}>{label}</button>)}</div>
        <section className="aura-panel mt-3 overflow-hidden rounded-lg">
          <div className="aura-thin-scroll overflow-x-auto"><table className="w-full min-w-[720px] text-left text-[10px] rtl:text-right"><thead><tr className="border-b border-[#173047] text-[#72879b]"><th className="px-4 py-3">{t.symbol}</th><th className="px-4 py-3">{t.price}</th><th className="px-4 py-3">{t.change24}</th><th className="px-4 py-3">{t.quote}</th></tr></thead><tbody>{visible.map(item => <tr key={item.symbol} onClick={() => setSelectedSymbol(item.symbol)} className={`cursor-pointer border-b border-[#10283c] hover:bg-[#081827] ${selectedSymbol === item.symbol ? 'bg-[#071a2b]' : ''}`}><td className="px-4 py-3 aura-mono font-semibold text-white">{item.symbol}</td><td className="px-4 py-3 aura-mono text-[#c3d0dc]">{formatPrice(item.price,item.symbol)}</td><td className={`px-4 py-3 aura-mono ${pnlClass(item.change_percent)}`}>{formatPct(item.change_percent)}</td><td className="px-4 py-1"><TinySparkline values={item.sparkline} positive={item.change_percent >= 0} /></td></tr>)}</tbody></table></div>
        </section>
      </div>
    </main>
  );
}

export default function TradingTerminal() {
  const [lang, setLang] = useState<Language>('en');
  const [view, setView] = useState<View>('terminal');
  const [selectedSymbol, setSelectedSymbol] = useState('EURUSD');
  const [streamState, setStreamState] = useState<StreamState>('reconnecting');
  const [runtime, setRuntime] = useState<RuntimeState>(EMPTY_RUNTIME);
  const [signal, setSignal] = useState<Signal>(EMPTY_SIGNAL);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio>(EMPTY_PORTFOLIO);
  const [markets, setMarkets] = useState<MarketItem[]>([]);
  const [riskPercent, setRiskPercent] = useState(1);
  const [sizingPreview, setSizingPreview] = useState<PositionSizePreview | null>(null);
  const [operatorKey, setOperatorKey] = useState('');
  const executionIdempotencyKey = useRef<string | null>(null);
  const [executing, setExecuting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const t = translations[lang];
  const isRtl = lang === 'fa';

  useEffect(() => {
    const media = window.matchMedia('(max-width: 767px)');
    const sync = () => setIsMobile(media.matches);
    sync();
    media.addEventListener('change', sync);
    return () => media.removeEventListener('change', sync);
  }, []);

  useEffect(() => {
    const saved = typeof window !== 'undefined' ? window.localStorage.getItem('aura-language') : null;
    if (saved === 'fa' || saved === 'en') setLang(saved);
  }, []);
  useEffect(() => { if (typeof window !== 'undefined') window.localStorage.setItem('aura-language', lang); }, [lang]);

  useEffect(() => {
    let alive = true;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const hydrate = async () => {
      try {
        const [healthRes, marketRes, portfolioRes] = await Promise.all([
          fetch(`${apiBase}/api/health`), fetch(`${apiBase}/api/market/${selectedSymbol}`), fetch(`${apiBase}/api/portfolio`),
        ]);
        if (!healthRes.ok || !marketRes.ok || !portfolioRes.ok) throw new Error('AURA API unavailable');
        const health = await healthRes.json(); const market = await marketRes.json(); const pf = await portfolioRes.json();
        if (!alive) return;
        setRuntime({ execution_mode: health.execution_mode, market_data_source: market.market_data_source, market_status: market.market_status, max_risk_percent: health.max_risk_percent, active_session: health.active_session, broker: health.broker, capabilities: health.capabilities, news_guard: health.news_guard, risk_guard: health.risk_guard });
        setSignal(market.signal); setCandles(market.candles || []); setPortfolio(pf);
      } catch { if (alive) setStreamState('offline'); }
    };
    const connect = () => {
      if (!alive) return;
      setStreamState('reconnecting');
      socket = new WebSocket(`${wsBase}/ws/signals?symbol=${encodeURIComponent(selectedSymbol)}`);
      socket.onopen = () => alive && setStreamState('connected');
      socket.onmessage = event => {
        if (!alive) return;
        try {
          const payload = JSON.parse(event.data);
          setRuntime({ execution_mode: payload.execution_mode, market_data_source: payload.market_data_source, market_status: payload.market_status, max_risk_percent: payload.max_risk_percent, active_session: payload.active_session, broker: payload.broker, capabilities: payload.capabilities, news_guard: payload.news_guard, risk_guard: payload.risk_guard });
          setSignal(payload.signal); setCandles(payload.candles || []); if (payload.portfolio) setPortfolio(payload.portfolio);
        } catch { /* malformed frame */ }
      };
      socket.onerror = () => alive && setStreamState('offline');
      socket.onclose = () => { if (!alive) return; setStreamState('reconnecting'); timer = setTimeout(connect, 2500); };
    };
    hydrate(); connect();
    return () => { alive = false; if (timer) clearTimeout(timer); socket?.close(); };
  }, [selectedSymbol]);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try { const res = await fetch(`${apiBase}/api/markets`); if (!res.ok) return; const data = await res.json(); if (alive) setMarkets(data.items || []); } catch { /* keep old board */ }
    };
    load(); const id = setInterval(load, 15000); return () => { alive = false; clearInterval(id); };
  }, []);

  useEffect(() => {
    if (signal.status !== 'A_PLUS_SETUP' || !signal.action || !signal.entry || !signal.sl) {
      setSizingPreview(null);
      return;
    }
    const controller = new AbortController();
    const preview = async () => {
      try {
        const res = await fetch(`${apiBase}/api/risk/preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({ symbol: signal.symbol, action: signal.action, entry: signal.entry, sl: signal.sl, risk_percent: riskPercent }),
        });
        if (!res.ok) { setSizingPreview(null); return; }
        setSizingPreview(await res.json());
      } catch (error) {
        if ((error as Error).name !== 'AbortError') setSizingPreview(null);
      }
    };
    preview();
    return () => controller.abort();
  }, [signal.symbol, signal.status, signal.action, signal.entry, signal.sl, riskPercent, portfolio.account.balance]);

  const refreshPortfolio = async () => {
    try { const res = await fetch(`${apiBase}/api/portfolio`); if (res.ok) setPortfolio(await res.json()); } catch { /* no-op */ }
  };

  const execute = async () => {
    if (signal.status !== 'A_PLUS_SETUP' || !signal.action || !signal.entry || !signal.sl || !signal.tp) return;
    if (!executionIdempotencyKey.current) {
      executionIdempotencyKey.current = globalThis.crypto?.randomUUID?.() || `aura-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
    const requestKey = executionIdempotencyKey.current;
    setExecuting(true);
    try {
      const headers: Record<string,string> = {
        'Content-Type': 'application/json',
        'Idempotency-Key': requestKey,
      };
      if (runtime.execution_mode === 'LIVE' && operatorKey.trim()) {
        headers['X-AURA-EXECUTION-KEY'] = operatorKey.trim();
      }
      const response = await fetch(`${apiBase}/api/trade/execute`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          symbol: signal.symbol,
          action: signal.action,
          entry: signal.entry,
          sl: signal.sl,
          tp: signal.tp,
          risk_percent: riskPercent,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        const detail = typeof result.detail === 'string' ? result.detail : result.detail?.message || 'Execution rejected';
        const deterministic = [401, 422, 423, 428].includes(response.status);
        if (deterministic) executionIdempotencyKey.current = null;
        throw new Error(detail);
      }
      executionIdempotencyKey.current = null;
      setToast(`${result.status} · ${result.ledger_order_id || result.order_id} · ${result.lots} lots`);
      await refreshPortfolio();
    } catch (error) {
      // Keep the same key after network/5xx/409 uncertainty. A retry can then recover
      // the worker result without creating a second live order.
      setToast(error instanceof Error ? error.message : 'Execution failed');
    } finally {
      setExecuting(false);
    }
  };

  const closePosition = async (id: string) => {
    try { const res = await fetch(`${apiBase}/api/positions/${id}/close`, { method: 'POST' }); const data = await res.json(); if (!res.ok) throw new Error(data.detail || 'Close rejected'); setToast(`CLOSED · ${id} · ${formatMoney(data.realized_pnl)}`); if (data.portfolio) setPortfolio(data.portfolio); else await refreshPortfolio(); }
    catch (error) { setToast(error instanceof Error ? error.message : 'Unable to close position'); }
  };

  const selectedMarket = markets.find(item => item.symbol === selectedSymbol);
  const current = candles[candles.length - 1]?.close || selectedMarket?.price;
  const modeNote = runtime.execution_mode === 'LIVE' ? t.liveModeNote : t.paperModeNote;

  return (
    <div className={`aura-app flex min-h-screen w-full overflow-hidden text-[#eaf2f8] lg:h-screen ${isRtl ? 'dir-rtl' : 'dir-ltr'}`} dir={isRtl ? 'rtl' : 'ltr'}>
      <Sidebar view={view} setView={setView} lang={lang} setLang={setLang} t={t} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar runtime={runtime} portfolio={portfolio} lang={lang} setLang={setLang} t={t} />
        <WatchlistStrip items={markets} selectedSymbol={selectedSymbol} setSelectedSymbol={(s) => { setSelectedSymbol(s); setView('terminal'); }} />

        {view === 'markets' ? <MarketsView items={markets} selectedSymbol={selectedSymbol} setSelectedSymbol={(s) => { setSelectedSymbol(s); setView('terminal'); }} t={t} />
        : view === 'signals' ? <SignalsView t={t} onOpenSymbol={(symbol) => { setSelectedSymbol(symbol); setView('terminal'); }} />
        : view === 'auto-trade' ? <AutoTradeView t={t} />
        : view === 'positions' ? <PositionsView t={t} />
        : view === 'orders' ? <OrdersView t={t} />
        : view === 'performance' ? <PerformanceView t={t} />
        : view === 'analytics' ? <AnalyticsView t={t} />
        : view === 'news-guard' ? <NewsGuardView t={t} />
        : view === 'calendar' ? <CalendarView t={t} />
        : view === 'backtesting' ? <BacktestingView selectedSymbol={selectedSymbol} t={t} />
        : isMobile ? (
          <MobileTerminalView candles={candles} signal={signal} runtime={runtime} portfolio={portfolio} sizing={sizingPreview} riskPercent={riskPercent} setRiskPercent={setRiskPercent} operatorKey={operatorKey} setOperatorKey={setOperatorKey} executing={executing} onExecute={execute} streamState={streamState} t={t} />
        ) : (
          <main className="aura-thin-scroll min-h-0 flex-1 overflow-y-auto bg-[#020b14] p-2 pb-20 md:p-2.5 xl:pb-2.5">
            <div className="aura-command-grid grid min-h-[510px] gap-2 lg:grid-cols-[minmax(0,1fr)_292px] xl:grid-cols-[minmax(0,1fr)_300px_210px]">
              <section className="aura-panel min-w-0 overflow-hidden rounded-lg">
                <ChartHeader symbol={selectedSymbol} t={t} />
                <div className="h-[395px] min-h-[330px] xl:h-[425px]"><TerminalChart candles={candles} signal={signal} source={runtime.market_data_source} streamState={streamState} t={t} /></div>
                <div className="flex h-8 items-center justify-between border-t border-[#173047]/70 bg-[#04111c] px-3 text-[8px] text-[#71869b]"><div className="flex gap-4"><span>1D</span><span>5D</span><span>1M</span><span>3M</span><span>6M</span><span>YTD</span><span>1Y</span><span>All</span></div><div className="flex items-center gap-3"><span className="hidden sm:inline">{utcClock()} (UTC)</span><span>%</span><span className="text-[#54a9ed]">log</span><span className="text-[#54a9ed]">auto</span></div></div>
              </section>
              <div className="grid min-w-0 gap-2 md:grid-cols-2 lg:grid-cols-1 xl:flex xl:flex-col"><SignalCard signal={signal} t={t} /><ExecuteCard signal={signal} portfolio={portfolio} runtime={runtime} sizing={sizingPreview} riskPercent={riskPercent} setRiskPercent={setRiskPercent} operatorKey={operatorKey} setOperatorKey={setOperatorKey} executing={executing} onExecute={execute} t={t} /></div>
              <StatusColumn runtime={runtime} portfolio={portfolio} signal={signal} sizing={sizingPreview} riskPercent={riskPercent} t={t} />
            </div>

            <div className="mt-2 grid gap-2 lg:grid-cols-[minmax(0,1fr)_270px]"><PositionsPanel portfolio={portfolio} onClose={closePosition} t={t} /><RecentSignals signal={signal} portfolio={portfolio} t={t} /></div>

            <div className="mt-2 flex items-center justify-between px-1 pb-1 text-[8px] text-[#4f667b]"><span>{modeNote}</span><span className="hidden sm:flex items-center gap-2"><Radio className={`h-3 w-3 ${streamState === 'connected' ? 'text-[#2ae9bd]' : 'text-[#ffb14a]'}`} />{streamState === 'connected' ? t.connected : streamState === 'reconnecting' ? t.reconnecting : t.offline} · {runtime.market_data_source} · {current ? formatPrice(current, selectedSymbol) : '—'}</span></div>
          </main>
        )}

        <nav className="aura-mobile-bottom fixed bottom-0 left-0 right-0 z-40 grid grid-cols-4 border-t border-[#173047] px-3 pt-2 xl:hidden">
          {[[t.terminal,CandlestickChart,'terminal'],[t.markets,BarChart3,'markets'],[t.signals,Activity,'signals'],[t.positions,WalletCards,'positions']].map(([label, Icon, target], i) => <button key={`${label}-${i}`} onClick={() => setView(target as View)} className={`flex flex-col items-center gap-1 py-1 text-[8px] ${view === target ? 'text-[#2ae9bd]' : 'text-[#6f8498]'}`}><Icon className="h-4 w-4" /><span>{label as string}</span></button>)}
        </nav>
      </div>

      {toast && <div className="fixed bottom-16 left-1/2 z-50 flex max-w-[90vw] -translate-x-1/2 items-center gap-2 rounded-lg border border-[#24506d] bg-[#071727]/95 px-4 py-3 text-[10px] text-[#d7e7f4] shadow-2xl backdrop-blur-xl xl:bottom-5"><Zap className="h-3.5 w-3.5 text-[#2ae9bd]" /><span className="aura-mono">{toast}</span><button onClick={() => setToast(null)} className="ml-2 text-[#71869b] hover:text-white rtl:ml-0 rtl:mr-2"><X className="h-3.5 w-3.5" /></button></div>}
    </div>
  );
}
