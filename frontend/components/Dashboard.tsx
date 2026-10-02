import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, BarChart3, BrainCircuit, CalendarDays, Database, Gauge, Globe2, ListOrdered, Radio,
} from 'lucide-react';
import { Dictionary, Language, translations } from '../locales/dictionary';
import {
  AlertsFeed, CalendarPanel, RiskHeatmap, SignalLog, StatsStrip, WatchlistGrid,
} from './panels';
import SymbolDetail from './SymbolDetail';
import { recLabel, TradeCallHistory, TradeDeskDetail, TradeDeskList } from './TradeDesk';
import type {
  AlertItem, CalendarEvent, HealthPayload, MarketRecord, SignalEvent, Stats24h, TradeAnalysis, TradeCall,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_VERTEX_API_URL || 'http://localhost:8000';
const WS_BASE = API_BASE.replace(/^http/, 'ws');
type Tab = 'overview' | 'desk' | 'risk' | 'alerts' | 'signals' | 'calendar' | 'sources';

async function safeJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export default function Dashboard() {
  const [lang, setLang] = useState<Language>('en');
  const [tab, setTab] = useState<Tab>('overview');
  const [records, setRecords] = useState<MarketRecord[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [candles, setCandles] = useState<any[]>([]);
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

  const t = translations[lang] as Dictionary;
  const dir = lang === 'fa' ? 'rtl' : 'ltr';
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    document.documentElement.dir = dir;
    document.documentElement.lang = lang;
  }, [dir, lang]);

  const refreshSecondary = useCallback(async () => {
    const [alertData, signalData, statsData, calendarData, healthData, analysisData, tradeCallData] = await Promise.all([
      safeJson<{ items: AlertItem[] }>(`${API_BASE}/api/alerts?limit=40`),
      safeJson<{ items: SignalEvent[] }>(`${API_BASE}/api/signals/history?limit=30`),
      safeJson<Stats24h>(`${API_BASE}/api/stats/24h`),
      safeJson<{ configured: boolean; events: CalendarEvent[] }>(`${API_BASE}/api/calendar`),
      safeJson<HealthPayload>(`${API_BASE}/api/health`),
      safeJson<{ items: TradeAnalysis[] }>(`${API_BASE}/api/analysis/overview`),
      safeJson<{ items: TradeCall[] }>(`${API_BASE}/api/trade-calls?limit=30`),
    ]);
    if (alertData) setAlerts(alertData.items);
    if (signalData) setSignalEvents(signalData.items);
    if (statsData) setStats(statsData);
    if (calendarData) { setCalendarConfigured(calendarData.configured); setCalendarEvents(calendarData.events || []); }
    if (healthData) setHealth(healthData);
    if (analysisData) {
      setAnalyses(analysisData.items);
      setDeskSymbol((prev) => prev || analysisData.items[0]?.symbol || null);
    }
    if (tradeCallData) setTradeCalls(tradeCallData.items);
  }, []);

  useEffect(() => {
    refreshSecondary();
    const interval = setInterval(refreshSecondary, 20000);
    return () => clearInterval(interval);
  }, [refreshSecondary]);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout>;

    function connect() {
      setConnection('connecting');
      const ws = new WebSocket(`${WS_BASE}/ws/live`);
      wsRef.current = ws;
      ws.onopen = () => !cancelled && setConnection('connected');
      ws.onmessage = (event) => {
        if (cancelled) return;
        try {
          const payload = JSON.parse(event.data);
          setRecords(payload.items || []);
          setSelected((prev) => prev || payload.items?.[0]?.symbol || null);
        } catch { /* ignore malformed frame */ }
      };
      ws.onclose = () => {
        if (cancelled) return;
        setConnection('offline');
        retryTimer = setTimeout(connect, 4000);
      };
      ws.onerror = () => ws.close();
    }
    connect();
    return () => { cancelled = true; clearTimeout(retryTimer); wsRef.current?.close(); };
  }, []);

  useEffect(() => {
    if (!selected) return;
    safeJson<{ candles: any[] }>(`${API_BASE}/api/market/${selected}?limit=200`).then((data) => {
      if (data) setCandles(data.candles || []);
    });
  }, [selected]);

  const selectedRecord = useMemo(() => records.find((r) => r.symbol === selected) || null, [records, selected]);
  const selectedAnalysis = useMemo(() => analyses.find((a) => a.symbol === deskSymbol) || null, [analyses, deskSymbol]);
  const topCall = useMemo(() => {
    const actionable = analyses.filter((a) => a.recommendation === 'BUY' || a.recommendation === 'SELL');
    return actionable.sort((a, b) => b.probability_percent - a.probability_percent)[0] || null;
  }, [analyses]);

  const nav: [string, any, Tab][] = [
    [t.overview, BarChart3, 'overview'],
    [t.tradeDesk, BrainCircuit, 'desk'],
    [t.riskHeatmap, Gauge, 'risk'],
    [t.alerts, AlertTriangle, 'alerts'],
    [t.signals, ListOrdered, 'signals'],
    [t.calendar, CalendarDays, 'calendar'],
    [t.settings, Database, 'sources'],
  ];

  return (
    <div dir={dir} className="flex min-h-screen flex-col bg-[#020810]">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[#15293c] bg-[#03101a]/95 px-4">
        <div className="flex items-center gap-2">
          <svg viewBox="0 0 32 32" className="h-6 w-6" aria-hidden="true">
            <path d="M6 26 16 6l10 20" stroke="#2e93ff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            <path d="M11 20h10" stroke="#2ae9bd" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
          <div>
            <div className="text-[15px] font-bold tracking-wide text-white">{t.brand}</div>
            <div className="hidden text-[8px] text-[#6f8498] sm:block">{t.tagline}</div>
          </div>
        </div>
        <nav className="vx-thin-scroll ml-4 flex flex-1 items-center gap-1 overflow-x-auto rtl:ml-0 rtl:mr-4">
          {nav.map(([label, Icon, key]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-[10px] font-medium transition ${tab === key ? 'bg-[#123152] text-white' : 'text-[#8ca1b5] hover:bg-[#0b1c2c] hover:text-white'}`}
            >
              <Icon className="h-3.5 w-3.5" />{label}
            </button>
          ))}
        </nav>
        <div className={`hidden items-center gap-1.5 rounded-md px-2 py-1 text-[9px] font-semibold sm:flex ${connection === 'connected' ? 'bg-[#0c553f]/40 text-[#2ae9bd]' : connection === 'connecting' ? 'bg-[#3a2a10]/50 text-[#ffb24a]' : 'bg-[#3a1420]/50 text-[#ff5a72]'}`}>
          <Radio className="h-3 w-3" />{connection === 'connected' ? t.live : connection === 'connecting' ? t.connecting : t.offline}
        </div>
        <button
          onClick={() => setLang(lang === 'en' ? 'fa' : 'en')}
          className="flex h-8 items-center gap-1.5 rounded-md border border-[#17344e] px-2 text-[10px] text-[#8ca1b5] hover:text-white"
        >
          <Globe2 className="h-3.5 w-3.5" />{lang === 'en' ? 'FA' : 'EN'}
        </button>
      </header>

      <main className="flex-1 p-3">
        {tab === 'overview' && (
          <div className="space-y-3">
            {topCall && (
              <button
                onClick={() => { setTab('desk'); setDeskSymbol(topCall.symbol); }}
                className={`vx-panel flex w-full flex-wrap items-center gap-3 rounded-lg border-l-4 p-3 text-left transition hover:brightness-110 rtl:border-l-0 rtl:border-r-4 rtl:text-right ${topCall.recommendation === 'BUY' ? 'border-l-[#2ae9bd] rtl:border-r-[#2ae9bd]' : 'border-l-[#ff5a72] rtl:border-r-[#ff5a72]'}`}
              >
                <BrainCircuit className={`h-5 w-5 shrink-0 ${topCall.recommendation === 'BUY' ? 'text-[#2ae9bd]' : 'text-[#ff5a72]'}`} />
                <div className="flex-1">
                  <div className="text-[10px] text-[#8ca1b5]">{t.tradeDesk}</div>
                  <div className="vx-mono text-[12px] font-semibold text-white">
                    {topCall.symbol} · <span className={topCall.recommendation === 'BUY' ? 'text-[#2ae9bd]' : 'text-[#ff5a72]'}>{recLabel(topCall.recommendation, t)}</span> · {topCall.probability_percent}% {t.probability.toLowerCase()} · {t.suggestedRisk} {topCall.suggested_risk_percent}%
                  </div>
                </div>
              </button>
            )}
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-[300px_1fr_320px]">
              <div className="space-y-3">
                <StatsStrip stats={stats} t={t} />
                <WatchlistGrid records={records} selected={selected} onSelect={setSelected} t={t} />
              </div>
              <SymbolDetail record={selectedRecord} candles={candles} t={t} />
              <div className="space-y-3">
                <AlertsFeed alerts={alerts.slice(0, 8)} t={t} />
                <CalendarPanel configured={calendarConfigured} events={calendarEvents.slice(0, 5)} t={t} />
              </div>
            </div>
          </div>
        )}

        {tab === 'desk' && (
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-[300px_1fr]">
            <TradeDeskList analyses={analyses} selected={deskSymbol} onSelect={setDeskSymbol} t={t} />
            <div className="space-y-3">
              <TradeDeskDetail analysis={selectedAnalysis} t={t} />
              <TradeCallHistory calls={tradeCalls} t={t} />
            </div>
          </div>
        )}

        {tab === 'risk' && (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <RiskHeatmap records={records} t={t} />
            <StatsStrip stats={stats} t={t} />
          </div>
        )}

        {tab === 'alerts' && <AlertsFeed alerts={alerts} t={t} />}
        {tab === 'signals' && <SignalLog events={signalEvents} t={t} />}
        {tab === 'calendar' && <CalendarPanel configured={calendarConfigured} events={calendarEvents} t={t} />}

        {tab === 'sources' && (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <div className="vx-panel rounded-lg p-4">
              <h3 className="mb-3 text-[12px] font-semibold text-white">{t.dataSources}</h3>
              <div className="space-y-3 text-[10px]">
                <div className="rounded-md border border-[#15293c] bg-[#081522] p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[#c3d2df]">{t.crypto}</span>
                    <span className={`rounded px-2 py-0.5 text-[8px] font-semibold ${health?.data_status.crypto.healthy ? 'bg-[#0c553f]/40 text-[#2ae9bd]' : 'bg-[#3a1420]/40 text-[#ff5a72]'}`}>
                      {health?.data_status.crypto.healthy ? t.live : t.offline}
                    </span>
                  </div>
                  <p className="mt-1 text-[9px] text-[#8598aa]">{t.cryptoSource}</p>
                </div>
                <div className="rounded-md border border-[#15293c] bg-[#081522] p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[#c3d2df]">{t.forexSource}</span>
                    <span className={`rounded px-2 py-0.5 text-[8px] font-semibold ${health?.data_status.forex.configured ? 'bg-[#0c553f]/40 text-[#2ae9bd]' : 'bg-[#3a2a10]/40 text-[#ffb24a]'}`}>
                      {health?.data_status.forex.configured ? t.live : t.notConfigured}
                    </span>
                  </div>
                  <p className="mt-1 text-[9px] text-[#8598aa]">{t.forexNotConfigured}</p>
                </div>
                <div className="rounded-md border border-[#15293c] bg-[#081522] p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[#c3d2df]">{t.newsSource}</span>
                    <span className={`rounded px-2 py-0.5 text-[8px] font-semibold ${health?.news_guard.configured ? 'bg-[#0c553f]/40 text-[#2ae9bd]' : 'bg-[#3a2a10]/40 text-[#ffb24a]'}`}>
                      {health?.news_guard.configured ? t.live : t.notConfigured}
                    </span>
                  </div>
                  <p className="mt-1 text-[9px] text-[#8598aa]">{t.newsNotConfigured}</p>
                </div>
                <div className="rounded-md border border-[#15293c] bg-[#081522] p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[#c3d2df]">Telegram</span>
                    <span className={`rounded px-2 py-0.5 text-[8px] font-semibold ${health?.telegram_configured ? 'bg-[#0c553f]/40 text-[#2ae9bd]' : 'bg-[#3a2a10]/40 text-[#ffb24a]'}`}>
                      {health?.telegram_configured ? t.live : t.notConfigured}
                    </span>
                  </div>
                  <p className="mt-1 text-[9px] text-[#8598aa]">{health?.telegram_configured ? t.telegramConfigured : t.telegramNotConfigured}</p>
                </div>
              </div>
            </div>
            <div className="vx-panel rounded-lg p-4">
              <h3 className="mb-3 flex items-center gap-2 text-[12px] font-semibold text-white"><Activity className="h-3.5 w-3.5" />{t.uptime}</h3>
              <div className="grid grid-cols-2 gap-2 text-[10px]">
                <div className="rounded-md border border-[#15293c] bg-[#081522] p-3">
                  <div className="text-[#71869b]">{t.uptime}</div>
                  <div className="vx-mono mt-1 text-white">{health ? `${Math.floor(health.uptime_seconds / 60)} min` : '—'}</div>
                </div>
                <div className="rounded-md border border-[#15293c] bg-[#081522] p-3">
                  <div className="text-[#71869b]">{t.scans24h}</div>
                  <div className="vx-mono mt-1 text-white">{health?.scan_count ?? '—'}</div>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      <footer className="border-t border-[#15293c] bg-[#03101a]/95 px-4 py-2 text-center text-[8px] leading-4 text-[#5f7589]">
        {t.disclaimer}
      </footer>
    </div>
  );
}
