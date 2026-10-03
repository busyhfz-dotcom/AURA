import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, BarChart3, Bell, BrainCircuit, CalendarDays, ChevronRight,
  Database, Gauge, Globe2, LayoutDashboard, ListOrdered, Menu, Search, ShieldCheck, X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Dictionary, Language, translations } from '../locales/dictionary';
import {
  AlertsFeed, CalendarPanel, RiskHeatmap, SignalLog, StatsStrip, WatchlistGrid, formatPct, formatPrice,
} from './panels';
import { AnalysisSummary, ConnectionNotice, NewsGuardCard, SourceHealth } from './TerminalPanels';
import SymbolDetail from './SymbolDetail';
import { TradeCallHistory, TradeDeskDetail, TradeDeskList } from './TradeDesk';
import type {
  AlertItem, CalendarEvent, HealthPayload, MarketRecord, SignalEvent, Stats24h, TradeAnalysis, TradeCall,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_VERTEX_API_URL || 'http://localhost:8000';
const WS_BASE = API_BASE.replace(/^http/, 'ws');
type Tab = 'overview' | 'markets' | 'desk' | 'risk' | 'alerts' | 'signals' | 'calendar' | 'sources';
type Candle = { time: number; open: number; high: number; low: number; close: number };

async function safeJson<T>(url: string): Promise<T | null> {
  try {
    const response = await fetch(url);
    return response.ok ? await response.json() as T : null;
  } catch {
    return null;
  }
}

function BrandMark() {
  return (
    <span className="vx-brand-mark" aria-hidden="true">
      <svg viewBox="0 0 36 36" fill="none">
        <path d="M5 28 16.7 5.5c.5-1 1.9-1 2.5 0L31 28" stroke="#2e93ff" strokeWidth="3.8" strokeLinecap="round" strokeLinejoin="round" />
        <path d="m12.4 21.6 5.6-9.9 5.6 9.9M11.2 26.5 18 20l6.8 6.5" stroke="#19dec2" strokeWidth="2.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

function NavButton({
  label, icon: Icon, active, onClick, compact = false,
}: { label: string; icon: LucideIcon; active: boolean; onClick: () => void; compact?: boolean }) {
  return (
    <button type="button" onClick={onClick} aria-current={active ? 'page' : undefined}
      className={'vx-nav-button ' + (active ? 'vx-nav-active ' : '') + (compact ? 'vx-nav-compact' : '')}>
      <Icon size={17} strokeWidth={active ? 2 : 1.7} />
      <span>{label}</span>
    </button>
  );
}

export default function Dashboard() {
  const [lang, setLang] = useState<Language>('en');
  const [tab, setTab] = useState<Tab>('overview');
  const [records, setRecords] = useState<MarketRecord[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [signalEvents, setSignalEvents] = useState<SignalEvent[]>([]);
  const [stats, setStats] = useState<Stats24h | null>(null);
  const [calendarEvents, setCalendarEvents] = useState<CalendarEvent[]>([]);
  const [calendarConfigured, setCalendarConfigured] = useState(false);
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [connection, setConnection] = useState<'connected' | 'connecting' | 'offline'>('connecting');
  const [analyses, setAnalyses] = useState<TradeAnalysis[]>([]);
  const [tradeCalls, setTradeCalls] = useState<TradeCall[]>([]);
  const [deskSymbol, setDeskSymbol] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [mobileMenu, setMobileMenu] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const t = translations[lang] as Dictionary;
  const dir = lang === 'fa' ? 'rtl' : 'ltr';
  const selectedRecord = records.find((record) => record.symbol === selected) || null;
  const selectedAnalysis = analyses.find((analysis) => analysis.symbol === selected) || null;
  const deskAnalysis = analyses.find((analysis) => analysis.symbol === deskSymbol) || null;
  const deskRecord = records.find((record) => record.symbol === deskSymbol) || null;
  const unavailableSymbols = useMemo(
    () => new Set(records.filter((record) => !record.data_available).map((record) => record.symbol)),
    [records],
  );
  const filteredRecords = useMemo(
    () => records.filter((record) => record.symbol.toLowerCase().includes(search.trim().toLowerCase())),
    [records, search],
  );
  const newsUnavailable = health?.news_guard?.configured === true &&
    (!!health.news_guard.provider_error || (health.news_guard.safe === false && !health.news_guard.active));

  useEffect(() => {
    try {
      const saved = localStorage.getItem('vertex-language');
      if (saved === 'en' || saved === 'fa') setLang(saved);
    } catch { /* storage may be unavailable */ }
  }, []);

  useEffect(() => {
    document.documentElement.dir = dir;
    document.documentElement.lang = lang;
    try { localStorage.setItem('vertex-language', lang); } catch { /* storage may be unavailable */ }
  }, [dir, lang]);

  const refresh = useCallback(async () => {
    const [market, alertData, signalData, statsData, calendarData, healthData, analysisData, tradeCallData] = await Promise.all([
      safeJson<{ items: MarketRecord[] }>(API_BASE + '/api/market/overview'),
      safeJson<{ items: AlertItem[] }>(API_BASE + '/api/alerts?limit=40'),
      safeJson<{ items: SignalEvent[] }>(API_BASE + '/api/signals/history?limit=30'),
      safeJson<Stats24h>(API_BASE + '/api/stats/24h'),
      safeJson<{ configured: boolean; events: CalendarEvent[] }>(API_BASE + '/api/calendar'),
      safeJson<HealthPayload>(API_BASE + '/api/health'),
      safeJson<{ items: TradeAnalysis[] }>(API_BASE + '/api/analysis/overview'),
      safeJson<{ items: TradeCall[] }>(API_BASE + '/api/trade-calls?limit=30'),
    ]);
    if (market) {
      setRecords(market.items || []);
      setSelected((previous) => previous || market.items?.[0]?.symbol || null);
    }
    if (alertData) setAlerts(alertData.items || []);
    if (signalData) setSignalEvents(signalData.items || []);
    if (statsData) setStats(statsData);
    if (calendarData) {
      setCalendarConfigured(calendarData.configured);
      setCalendarEvents(calendarData.events || []);
    }
    if (healthData) setHealth(healthData);
    if (analysisData) {
      setAnalyses(analysisData.items || []);
      setDeskSymbol((previous) => previous || analysisData.items?.[0]?.symbol || null);
    }
    if (tradeCallData) setTradeCalls(tradeCallData.items || []);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 20000);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout>;
    function connect() {
      setConnection('connecting');
      const socket = new WebSocket(WS_BASE + '/ws/live');
      wsRef.current = socket;
      socket.onopen = () => { if (!cancelled) setConnection('connected'); };
      socket.onmessage = (event) => {
        if (cancelled) return;
        try {
          const payload = JSON.parse(event.data) as { items?: MarketRecord[] };
          if (Array.isArray(payload.items)) {
            setRecords(payload.items);
            setSelected((previous) => previous || payload.items?.[0]?.symbol || null);
          }
        } catch { /* ignore malformed frames */ }
      };
      socket.onclose = () => {
        if (cancelled) return;
        setConnection('offline');
        retryTimer = setTimeout(connect, 4000);
      };
      socket.onerror = () => socket.close();
    }
    connect();
    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      wsRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (!selected || selectedRecord?.data_available === false) {
      setCandles([]);
      return;
    }
    let cancelled = false;
    setCandles([]);
    safeJson<{ candles: Candle[] }>(API_BASE + '/api/market/' + encodeURIComponent(selected) + '?limit=200')
      .then((data) => { if (!cancelled) setCandles(data?.candles || []); });
    return () => { cancelled = true; };
  }, [selected, selectedRecord?.data_available]);

  const chooseSymbol = (symbol: string) => {
    setSelected(symbol);
    setDeskSymbol(symbol);
  };
  const chooseTab = (next: Tab) => {
    setTab(next);
    setMobileMenu(false);
  };
  const nav: { label: string; icon: LucideIcon; key: Tab }[] = [
    { label: t.terminal, icon: LayoutDashboard, key: 'overview' },
    { label: t.markets, icon: BarChart3, key: 'markets' },
    { label: t.tradeDesk, icon: BrainCircuit, key: 'desk' },
    { label: t.riskHeatmap, icon: Gauge, key: 'risk' },
    { label: t.alerts, icon: Bell, key: 'alerts' },
    { label: t.signals, icon: ListOrdered, key: 'signals' },
    { label: t.calendar, icon: CalendarDays, key: 'calendar' },
    { label: t.settings, icon: Database, key: 'sources' },
  ];

  return (
    <div dir={dir} className="vx-app-shell">
      <a className="vx-skip-link" href="#vertex-main">{t.terminal}</a>
      <aside className={'vx-sidebar ' + (mobileMenu ? 'vx-sidebar-open' : '')}>
        <div className="vx-sidebar-brand"><BrandMark /><div><strong>{t.brand}</strong><small>{t.tagline}</small></div></div>
        <div className="vx-sidebar-caption">{t.marketStatus}</div>
        <nav className="vx-side-nav" aria-label={t.terminal}>
          {nav.map((item) => <NavButton key={item.key} label={item.label} icon={item.icon} active={tab === item.key} onClick={() => chooseTab(item.key)} />)}
        </nav>
        <div className="vx-sidebar-bottom">
          <div className="vx-sidebar-note"><ShieldCheck size={17} /><span>{t.analysisOnly}</span></div>
          <div className="vx-sidebar-foot"><span>{t.brand}</span><span>© 2026</span></div>
        </div>
      </aside>

      <div className="vx-workspace">
        <header className="vx-topbar">
          <button type="button" className="vx-menu-toggle" aria-label={t.terminal} onClick={() => setMobileMenu(!mobileMenu)}>
            {mobileMenu ? <X size={20} /> : <Menu size={20} />}
          </button>
          <div className="vx-mobile-brand"><BrandMark /><strong>{t.brand}</strong></div>
          <label className="vx-search">
            <Search size={16} />
            <span className="sr-only">{t.searchMarkets}</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t.search} />
            {search && <button type="button" onClick={() => setSearch('')} aria-label={t.close}><X size={14} /></button>}
          </label>
          <div className="vx-top-actions">
            <ConnectionNotice connection={connection} t={t} />
            <span className="vx-top-divider" />
            <button type="button" className="vx-lang-button" onClick={() => setLang(lang === 'en' ? 'fa' : 'en')} aria-label={t.language}>
              <Globe2 size={16} /><span>{lang === 'en' ? 'FA' : 'EN'}</span>
            </button>
          </div>
        </header>

        <main id="vertex-main" className="vx-main">
          {(tab === 'overview' || tab === 'markets') && (
            <div className="vx-ticker-wrap">
              <div className="vx-ticker-label"><Activity size={14} /><span>{t.watchlist}</span></div>
              <div className="vx-ticker-strip" aria-label={t.watchlist}>
                {filteredRecords.length === 0 && <div className="vx-ticker-empty">{search ? t.searchEmpty : t.waitingForData}</div>}
                {filteredRecords.map((record) => {
                  const available = record.data_available;
                  const change = record.snapshot?.price_change_percent;
                  return (
                    <button type="button" key={record.symbol} onClick={() => chooseSymbol(record.symbol)}
                      aria-pressed={selected === record.symbol}
                      className={'vx-ticker ' + (selected === record.symbol ? 'vx-ticker-selected' : '')}>
                      <span className="vx-ticker-top"><strong className="vx-mono">{record.symbol}</strong>
                        <span className={available && typeof change === 'number' ? (change >= 0 ? 'vx-mint' : 'vx-red') : 'vx-muted'}>
                          {available ? formatPct(change) : t.dataUnavailable}
                        </span>
                      </span>
                      <span className="vx-ticker-bottom"><span className="vx-mono">{available ? formatPrice(record.snapshot?.last_price, record.symbol) : '—'}</span><span>{record.asset_class}</span></span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {tab === 'overview' && (
            <>
              <div className="vx-page-heading">
                <div><span className="vx-eyebrow">{t.tagline}</span><h1>{t.terminal}</h1></div>
                <span className="vx-heading-meta">{selectedRecord ? selectedRecord.symbol + ' · ' + selectedRecord.asset_class : t.selectSymbol}</span>
              </div>
              <div className="vx-terminal-grid">
                <div className="vx-chart-column">
                  <SymbolDetail record={selectedRecord} candles={candles} t={t} />
                </div>
                <div className="vx-rail">
                  <AnalysisSummary analysis={selectedAnalysis} record={selectedRecord} t={t} onOpenDesk={() => { setDeskSymbol(selected); chooseTab('desk'); }} />
                  <SourceHealth health={health} t={t} />
                  <NewsGuardCard health={health} record={selectedRecord} t={t} onOpenCalendar={() => chooseTab('calendar')} />
                </div>
              </div>
              <div className="vx-lower-grid">
                <SignalLog events={signalEvents.slice(0, 8)} t={t} />
                <AlertsFeed alerts={alerts.slice(0, 6)} t={t} />
              </div>
            </>
          )}

          {tab === 'markets' && (
            <div className="vx-content-grid">
              <WatchlistGrid records={filteredRecords} selected={selected} onSelect={chooseSymbol} t={t} />
              <SymbolDetail record={selectedRecord} candles={candles} t={t} />
            </div>
          )}
          {tab === 'desk' && (
            <div className="vx-content-grid">
              <TradeDeskList analyses={analyses} selected={deskSymbol} onSelect={setDeskSymbol} unavailableSymbols={unavailableSymbols} t={t} />
              <div className="vx-stack"><TradeDeskDetail analysis={deskAnalysis} unavailable={deskRecord?.data_available === false} t={t} /><TradeCallHistory calls={tradeCalls} t={t} /></div>
            </div>
          )}
          {tab === 'risk' && <div className="vx-content-grid"><RiskHeatmap records={records} t={t} /><StatsStrip stats={stats} t={t} /></div>}
          {tab === 'alerts' && <div className="vx-wide-panel"><AlertsFeed alerts={alerts} t={t} /></div>}
          {tab === 'signals' && <div className="vx-wide-panel"><SignalLog events={signalEvents} t={t} /></div>}
          {tab === 'calendar' && (
            <div className="vx-content-grid">
              <CalendarPanel configured={calendarConfigured} unavailable={newsUnavailable} events={calendarEvents} t={t} />
              <NewsGuardCard health={health} record={selectedRecord} t={t} onOpenCalendar={() => chooseTab('calendar')} />
            </div>
          )}
          {tab === 'sources' && (
            <div className="vx-content-grid">
              <SourceHealth health={health} t={t} />
              <div className="vx-stack">
                <NewsGuardCard health={health} record={selectedRecord} t={t} onOpenCalendar={() => chooseTab('calendar')} />
                <div className="vx-panel vx-side-card"><h2>{t.uptime}</h2><p className="vx-source-row"><span>{t.uptime}</span><strong className="vx-mono">{health ? Math.floor(health.uptime_seconds / 60) + ' min' : '—'}</strong></p></div>
              </div>
            </div>
          )}
        </main>
        <footer className="vx-footer"><AlertTriangle size={14} /><span>{t.disclaimer}</span></footer>
      </div>
      <nav className="vx-mobile-nav" aria-label={t.terminal}>
        {nav.filter((item) => ['overview', 'markets', 'desk', 'alerts'].includes(item.key)).map((item) => (
          <NavButton key={item.key} label={item.label} icon={item.icon} active={tab === item.key} onClick={() => chooseTab(item.key)} compact />
        ))}
        <button type="button" className="vx-mobile-more" onClick={() => setMobileMenu(true)} aria-label={t.settings}><ChevronRight size={18} /><span>{t.settings}</span></button>
      </nav>
      {mobileMenu && <button type="button" className="vx-sidebar-scrim" aria-label={t.close} onClick={() => setMobileMenu(false)} />}
    </div>
  );
}
