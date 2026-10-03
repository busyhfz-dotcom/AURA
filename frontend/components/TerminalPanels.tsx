import React from 'react';
import { Activity, ArrowUpRight, CheckCircle2, Clock3, ShieldAlert, ShieldCheck, WifiOff } from 'lucide-react';
import type { Dictionary } from '../locales/dictionary';
import type { HealthPayload, MarketRecord, TradeAnalysis } from './types';
import { formatPrice } from './panels';
import { recLabel } from './TradeDesk';

function StatePill({ state, label }: { state: 'ok' | 'warn' | 'bad'; label: string }) {
  return <span className={'vx-state vx-state-' + state}><span className="vx-state-dot" />{label}</span>;
}

function riskOverride(analysis: TradeAnalysis, record: MarketRecord | null, t: Dictionary): string | null {
  if (!analysis.override_reason) return null;
  if (record?.risk?.news_embargo_active || record?.news_guard?.active) return t.riskOverrideNews;
  if (analysis.risk_label === 'HIGH' || record?.risk?.risk_label === 'HIGH') return t.riskOverrideHigh;
  return t.riskOverrideOther;
}

export function AnalysisSummary({
  analysis, record, t, onOpenDesk,
}: {
  analysis: TradeAnalysis | null;
  record: MarketRecord | null;
  t: Dictionary;
  onOpenDesk: () => void;
}) {
  const unavailable = record?.data_available === false;
  const usable = !unavailable && !!analysis;
  const recommendation = usable ? analysis.recommendation : 'WAIT';
  const override = usable ? riskOverride(analysis, record, t) : null;
  const plan = usable && recommendation !== 'WAIT' ? analysis.entry_plan : null;
  const tone = recommendation === 'BUY' ? 'positive' : recommendation === 'SELL' ? 'negative' : 'neutral';

  return (
    <section className="vx-panel vx-summary" aria-label={t.analysis}>
      <div className="vx-section-head">
        <div>
          <span className="vx-eyebrow">{t.tradeDesk}</span>
          <h2>{t.analysis}</h2>
        </div>
        <span className="vx-quiet-badge"><Activity size={13} />{t.analysisOnly}</span>
      </div>
      <div className="vx-summary-call">
        <div>
          <span className={'vx-call vx-call-' + tone}>{recLabel(recommendation, t)}</span>
          <div className="vx-summary-symbol vx-mono">{record?.symbol || analysis?.symbol || '—'}</div>
        </div>
        <div className="vx-score">
          <span>{t.probability}</span>
          <strong className="vx-mono">{usable ? analysis.probability_percent + '%' : '—'}</strong>
        </div>
      </div>
      {!usable && (
        <p className="vx-inline-note vx-inline-note-warn">
          <WifiOff size={16} />{unavailable ? t.noMarketData : t.analysisPending}
        </p>
      )}
      {override && <p className="vx-inline-note vx-inline-note-warn"><ShieldAlert size={16} />{override}</p>}
      <div className="vx-plan-grid">
        <div><span>{t.entry}</span><strong className="vx-mono">{plan && analysis ? formatPrice(plan.entry, analysis.symbol) : '—'}</strong></div>
        <div><span>{t.stopLoss}</span><strong className="vx-mono vx-red">{plan && analysis ? formatPrice(plan.sl, analysis.symbol) : '—'}</strong></div>
        <div><span>{t.takeProfit}</span><strong className="vx-mono vx-mint">{plan && analysis ? formatPrice(plan.tp, analysis.symbol) : '—'}</strong></div>
      </div>
      {plan && analysis ? (
        <div className="vx-plan-meta"><span>{t.riskReward}: <b>{plan.rr}</b></span><span>{t.suggestedRisk}: <b>{analysis.suggested_risk_percent}%</b></span></div>
      ) : <p className="vx-muted vx-plan-note">{t.noEntryPlan}</p>}
      <button type="button" className="vx-primary-action" onClick={onOpenDesk}>
        {t.viewDesk}<ArrowUpRight size={16} />
      </button>
      <p className="vx-small-disclaimer">{t.analystDisclaimer}</p>
    </section>
  );
}

export function SourceHealth({
  health, t,
}: { health: HealthPayload | null; t: Dictionary }) {
  const cryptoOk = health?.data_status?.crypto?.healthy === true;
  const forex = health?.data_status?.forex;
  const forexOk = forex?.configured === true && forex?.healthy === true;
  const forexUnconfigured = forex?.configured === false;
  const unknown = health === null;
  return (
    <section className="vx-panel vx-side-card" aria-label={t.sourceStatus}>
      <div className="vx-section-head">
        <h2>{t.sourceStatus}</h2>
        <Activity size={17} className="vx-blue" />
      </div>
      <div className="vx-source-row">
        <div><strong>{t.crypto}</strong><span>Binance</span></div>
        <StatePill state={cryptoOk ? 'ok' : unknown ? 'warn' : 'bad'} label={cryptoOk ? t.dataHealthy : unknown ? t.unknownStatus : t.dataUnavailable} />
      </div>
      <div className="vx-source-row">
        <div><strong>{t.forex} / {t.metals}</strong><span>Twelve Data</span></div>
        <StatePill state={forexOk ? 'ok' : unknown || forexUnconfigured ? 'warn' : 'bad'} label={forexOk ? t.dataHealthy : unknown ? t.unknownStatus : forexUnconfigured ? t.providerSetup : t.dataUnavailable} />
      </div>
      <div className="vx-scan-counts">
        <div><span>{t.scanCrypto}</span><strong className="vx-mono">{health?.scan_counts_by_class?.crypto ?? '—'}</strong></div>
        <div><span>{t.scanForex}</span><strong className="vx-mono">{health?.scan_counts_by_class?.forex ?? '—'}</strong></div>
      </div>
      {!forexOk && <p className="vx-muted vx-source-note">{unknown ? t.sourceUnknown : forexUnconfigured ? t.forexNotConfigured : t.forexIssue}</p>}
    </section>
  );
}

export function NewsGuardCard({
  health, record, t, onOpenCalendar,
}: {
  health: HealthPayload | null;
  record: MarketRecord | null;
  t: Dictionary;
  onOpenCalendar: () => void;
}) {
  const guard = record?.news_guard || health?.news_guard;
  const active = guard?.active === true;
  const knownSafe = guard?.configured === true && guard?.safe === true && !guard?.provider_error && !active;
  const state = active ? 'bad' : knownSafe ? 'ok' : 'warn';
  const message = active ? t.newsActive : knownSafe ? t.newsClear : t.newsUnknown;
  return (
    <section className="vx-panel vx-side-card" aria-label={t.newsGuard}>
      <div className="vx-section-head">
        <h2>{t.newsGuard}</h2>
        <StatePill state={state} label={active ? t.newsEmbargo : knownSafe ? t.safeStatus : t.unknownStatus} />
      </div>
      <div className="vx-news-body">
        {active ? <ShieldAlert size={20} className="vx-red" /> : knownSafe ? <ShieldCheck size={20} className="vx-mint" /> : <Clock3 size={20} className="vx-amber" />}
        <p>{message}</p>
      </div>
      <button type="button" className="vx-secondary-action" onClick={onOpenCalendar}>{t.viewCalendar}<ArrowUpRight size={14} /></button>
    </section>
  );
}

export function ConnectionNotice({ connection, t }: { connection: 'connected' | 'connecting' | 'offline'; t: Dictionary }) {
  const ok = connection === 'connected';
  return (
    <span className={'vx-connection ' + (ok ? 'vx-connection-live' : 'vx-connection-offline')} role="status">
      {ok ? <CheckCircle2 size={13} /> : <WifiOff size={13} />}
      {ok ? t.live : connection === 'connecting' ? t.reconnecting : t.noConnection}
    </span>
  );
}
