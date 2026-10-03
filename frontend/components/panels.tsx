import React from 'react';
import { AlertTriangle, ShieldAlert, Sparkles, Newspaper } from 'lucide-react';
import type { Dictionary } from '../locales/dictionary';
import type { AlertItem, MarketRecord, SignalEvent, Stats24h, CalendarEvent } from './types';

export function formatPrice(value?: number | null, symbol = '') {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  if (symbol.includes('JPY')) return value.toFixed(3);
  if (value >= 1000) return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (value >= 20) return value.toFixed(2);
  return value.toFixed(5);
}

export function formatPct(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

export function riskColor(label: string) {
  switch (label) {
    case 'HIGH': return { text: 'text-[#ff5a72]', bg: 'bg-[#3a1420]', border: 'border-[#5c1f2e]' };
    case 'ELEVATED': return { text: 'text-[#ffb24a]', bg: 'bg-[#3a2a10]', border: 'border-[#5c421a]' };
    case 'MODERATE': return { text: 'text-[#7fc7ff]', bg: 'bg-[#132a3a]', border: 'border-[#1f4560]' };
    default: return { text: 'text-[#2ae9bd]', bg: 'bg-[#0e3129]', border: 'border-[#175943]' };
  }
}

export function StatsStrip({ stats, t }: { stats: Stats24h | null; t: Dictionary }) {
  const items = [
    { label: t.scans24h, value: stats?.total_scans ?? '—' },
    { label: t.entriesDetected, value: stats?.entries_detected ?? '—' },
    { label: t.alertsFired, value: Object.values(stats?.alerts_by_severity || {}).reduce((a, b) => a + b, 0) || (stats ? 0 : '—') },
  ];
  return (
    <div className="grid grid-cols-3 gap-2">
      {items.map((item) => (
        <div key={item.label} className="vx-panel rounded-lg p-3">
          <div className="text-[11px] text-[#7f93a6]">{item.label}</div>
          <div className="vx-mono mt-1 text-[18px] font-semibold text-white">{item.value}</div>
        </div>
      ))}
    </div>
  );
}

export function WatchlistGrid({
  records, selected, onSelect, t,
}: { records: MarketRecord[]; selected: string | null; onSelect: (s: string) => void; t: Dictionary }) {
  return (
    <div className="vx-panel rounded-lg p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[12px] font-semibold text-white">{t.watchlist}</h3>
        <span className="text-[11px] text-[#8ca1b5]">{records.length} {t.markets}</span>
      </div>
      <div className="vx-thin-scroll grid max-h-[420px] grid-cols-1 gap-1.5 overflow-y-auto sm:grid-cols-2">
        {records.length === 0 && <p className="py-8 text-center text-[12px] text-[#8ca1b5] sm:col-span-2">{t.waitingForData}</p>}
        {records.map((record) => {
          const risk = riskColor(record.risk?.risk_label || 'LOW');
          const positive = (record.snapshot?.price_change_percent ?? record.risk?.change_percent_24h ?? 0) >= 0;
          const active = selected === record.symbol;
          const ready = record.signal?.status === 'A_PLUS_SETUP';
          return (
            <button
              key={record.symbol}
              onClick={() => onSelect(record.symbol)}
              className={`vx-risk-cell rounded-md border p-2.5 text-left transition rtl:text-right ${active ? 'border-[#2e93ff] bg-[#0b2136]' : 'border-[#15293c] bg-[#081522] hover:border-[#24435d]'}`}
            >
              <div className="flex items-center justify-between">
                <span className="vx-mono text-[11px] font-semibold text-white">{record.symbol}</span>
                {ready && <Sparkles className="h-3 w-3 text-[#2ae9bd]" />}
              </div>
              <div className="mt-1 flex items-center justify-between">
                <span className="vx-mono text-[12px] text-[#c3d2df]">
                  {record.data_available ? formatPrice(record.snapshot?.last_price, record.symbol) : t.waitingForData}
                </span>
                <span className={`vx-mono text-[11px] ${positive ? 'text-[#2ae9bd]' : 'text-[#ff5a72]'}`}>
                  {record.data_available ? formatPct(record.snapshot?.price_change_percent ?? record.risk?.change_percent_24h) : '—'}
                </span>
              </div>
              <div className="mt-1.5 flex items-center gap-1.5">
                {record.data_available ? (
                  <span className={`rounded px-1.5 py-0.5 text-[12px] font-semibold ${risk.bg} ${risk.text} border ${risk.border}`}>
                    {(t as any)[record.risk?.risk_label?.toLowerCase()] || record.risk?.risk_label} · {record.risk?.risk_score ?? 0}
                  </span>
                ) : <span className="rounded border border-[#59412a] bg-[#302318] px-1.5 py-0.5 text-[12px] text-[#f8bc63]">{t.dataUnavailable}</span>}
                {record.risk?.news_embargo_active && <ShieldAlert className="h-3 w-3 text-[#ffb24a]" />}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function RiskHeatmap({ records, t }: { records: MarketRecord[]; t: Dictionary }) {
  const sorted = [...records].sort((a, b) => (b.risk?.risk_score || 0) - (a.risk?.risk_score || 0));
  return (
    <div className="vx-panel rounded-lg p-3">
      <h3 className="mb-2 text-[12px] font-semibold text-white">{t.riskHeatmap}</h3>
      <div className="vx-thin-scroll max-h-[300px] overflow-y-auto">
        <table className="w-full border-collapse text-left text-[11px] rtl:text-right">
          <thead>
            <tr className="border-b border-[#132b40] text-[#72879b]">
              <th className="py-1.5 pr-2">{t.symbol}</th>
              <th className="py-1.5 pr-2">{t.risk}</th>
              <th className="py-1.5 pr-2">{t.volatility}</th>
              <th className="py-1.5 pr-2">{t.change24h}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((record) => {
              if (!record.data_available) {
                return <tr key={record.symbol} className="border-b border-[#0f2233]"><td className="vx-mono py-2 pr-2 text-white">{record.symbol}</td><td colSpan={3} className="py-2 text-[#f8bc63]">{t.dataUnavailable}</td></tr>;
              }
              const risk = riskColor(record.risk?.risk_label || 'LOW');
              return (
                <tr key={record.symbol} className="border-b border-[#0f2233]">
                  <td className="vx-mono py-1.5 pr-2 text-white">{record.symbol}</td>
                  <td className="py-1.5 pr-2">
                    <div className="flex items-center gap-1.5">
                      <div className="h-1.5 w-16 rounded-full bg-[#152a3d]">
                        <div className={`h-1.5 rounded-full ${risk.text.replace('text-', 'bg-')}`} style={{ width: `${record.risk?.risk_score || 0}%` }} />
                      </div>
                      <span className={risk.text}>{record.risk?.risk_score ?? 0}</span>
                    </div>
                  </td>
                  <td className="py-1.5 pr-2 text-[#a8b7c5]">{record.risk?.volatility_state || '—'}</td>
                  <td className={`vx-mono py-1.5 pr-2 ${(record.risk?.change_percent_24h || 0) >= 0 ? 'text-[#2ae9bd]' : 'text-[#ff5a72]'}`}>
                    {formatPct(record.risk?.change_percent_24h)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function AlertsFeed({ alerts, t }: { alerts: AlertItem[]; t: Dictionary }) {
  const sevIcon = (severity: string) => {
    if (severity === 'HIGH') return <AlertTriangle className="h-3.5 w-3.5 text-[#ff5a72]" />;
    if (severity === 'MEDIUM') return <Newspaper className="h-3.5 w-3.5 text-[#ffb24a]" />;
    return <Sparkles className="h-3.5 w-3.5 text-[#2ae9bd]" />;
  };
  return (
    <div className="vx-panel rounded-lg p-3">
      <h3 className="mb-2 text-[12px] font-semibold text-white">{t.recentAlerts}</h3>
      <div className="vx-thin-scroll max-h-[340px] space-y-2 overflow-y-auto">
        {alerts.length === 0 && <div className="py-6 text-center text-[12px] text-[#5f7589]">{t.noAlerts}</div>}
        {alerts.map((alert) => {
          const legacyCall = alert.category === 'TRADE_CALL' && alert.metadata?.score_type !== 'UNCALIBRATED_CONFLUENCE';
          return (
          <div key={alert.id} className="flex items-start gap-2 rounded-md border border-[#15293c] bg-[#081522] p-2">
            <div className="mt-0.5">{sevIcon(alert.severity)}</div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[12px] font-semibold text-white">{legacyCall ? `${alert.symbol}: ${t.historicalCall}` : alert.title}</span>
                <span className="vx-mono shrink-0 text-[12px] text-[#5f7589]">{new Date(alert.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
              </div>
              <p className="mt-0.5 text-[11px] leading-4 text-[#9aabba]">{legacyCall ? t.legacyCall : alert.message}</p>
            </div>
          </div>
          );
        })}
      </div>
    </div>
  );
}

export function SignalLog({ events, t }: { events: SignalEvent[]; t: Dictionary }) {
  return (
    <div className="vx-panel rounded-lg p-3">
      <h3 className="mb-2 text-[12px] font-semibold text-white">{t.signals}</h3>
      <div className="vx-thin-scroll max-h-[260px] overflow-y-auto">
        <table className="w-full border-collapse text-left text-[11px] rtl:text-right">
          <thead>
            <tr className="border-b border-[#132b40] text-[#72879b]">
              <th className="py-1.5 pr-2">{t.symbol}</th>
              <th className="py-1.5 pr-2">{t.action}</th>
              <th className="py-1.5 pr-2">{t.entry}</th>
              <th className="py-1.5 pr-2">{t.confluence}</th>
              <th className="py-1.5 pr-2">{t.time}</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 && (
              <tr><td colSpan={5} className="py-6 text-center text-[12px] text-[#5f7589]">{t.noSignals}</td></tr>
            )}
            {events.map((event) => (
              <tr key={event.id} className="border-b border-[#0f2233]">
                <td className="vx-mono py-1.5 pr-2 text-white">{event.symbol}</td>
                <td className={`py-1.5 pr-2 font-semibold ${event.action === 'SELL' ? 'text-[#ff5a72]' : 'text-[#2ae9bd]'}`}>{event.action || '—'}</td>
                <td className="vx-mono py-1.5 pr-2 text-[#c3d2df]">{formatPrice(event.entry, event.symbol)}</td>
                <td className="vx-mono py-1.5 pr-2 text-[#c3d2df]">{event.confluence_score}</td>
                <td className="vx-mono py-1.5 pr-2 text-[#5f7589]">{new Date(event.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function CalendarPanel({ configured, unavailable = false, events, t }: { configured: boolean; unavailable?: boolean; events: CalendarEvent[]; t: Dictionary }) {
  return (
    <div className="vx-panel rounded-lg p-3">
      <h3 className="mb-2 text-[12px] font-semibold text-white">{t.calendar}</h3>
      {unavailable ? (
        <p className="py-4 text-center text-[11px] leading-5 text-[#f8bc63]">{t.newsUnknown}</p>
      ) : !configured ? (
        <p className="py-4 text-center text-[11px] leading-4 text-[#8598aa]">{t.newsNotConfigured}</p>
      ) : (
        <div className="vx-thin-scroll max-h-[220px] space-y-1.5 overflow-y-auto">
          {events.length === 0 && <div className="py-4 text-center text-[11px] text-[#5f7589]">—</div>}
          {events.map((event, i) => (
            <div key={`${event.event}-${i}`} className="flex items-center justify-between rounded-md border border-[#15293c] bg-[#081522] px-2 py-1.5 text-[11px]">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[#d7e2ec]">{event.event}</div>
                <div className="text-[12px] text-[#5f7589]">{event.currency || event.country || ''}</div>
              </div>
              <span className={`ml-2 shrink-0 rounded px-1.5 py-0.5 text-[12px] font-semibold rtl:ml-0 rtl:mr-2 ${event.impact === 'HIGH' ? 'bg-[#3a1420] text-[#ff5a72]' : 'bg-[#152a3d] text-[#7fa8c7]'}`}>{event.impact}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
