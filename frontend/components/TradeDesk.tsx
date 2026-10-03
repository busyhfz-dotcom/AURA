import React from 'react';
import { Ban, ShieldAlert, TrendingDown, TrendingUp } from 'lucide-react';
import type { Dictionary } from '../locales/dictionary';
import type { TradeAnalysis, TradeCall } from './types';
import { formatPrice, riskColor } from './panels';

function recBadge(recommendation: string) {
  if (recommendation === 'BUY') return { icon: TrendingUp, text: 'text-[#2ae9bd]', bg: 'bg-[#0e3129]', border: 'border-[#175943]' };
  if (recommendation === 'SELL') return { icon: TrendingDown, text: 'text-[#ff5a72]', bg: 'bg-[#3a1420]', border: 'border-[#5c1f2e]' };
  return { icon: Ban, text: 'text-[#8ca1b5]', bg: 'bg-[#132330]', border: 'border-[#1f3a4d]' };
}

export function recLabel(recommendation: string, t: Dictionary) {
  if (recommendation === 'BUY') return t.buy;
  if (recommendation === 'SELL') return t.sell;
  return t.wait;
}

export function TradeDeskList({
  analyses, selected, onSelect, unavailableSymbols, t,
}: { analyses: TradeAnalysis[]; selected: string | null; onSelect: (s: string) => void; unavailableSymbols?: Set<string>; t: Dictionary }) {
  const sorted = [...analyses].sort((a, b) => b.probability_percent - a.probability_percent);
  return (
    <div className="vx-panel rounded-lg p-3">
      <h3 className="mb-2 text-[12px] font-semibold text-white">{t.tradeDesk}</h3>
      <div className="vx-thin-scroll max-h-[440px] space-y-1.5 overflow-y-auto">
        {sorted.map((analysis) => {
          const badge = recBadge(analysis.recommendation);
          const Icon = badge.icon;
          return (
            <button
              key={analysis.symbol}
              onClick={() => onSelect(analysis.symbol)}
              className={`w-full rounded-md border p-2.5 text-left transition rtl:text-right ${selected === analysis.symbol ? 'border-[#2e93ff] bg-[#0b2136]' : 'border-[#15293c] bg-[#081522] hover:border-[#24435d]'}`}
            >
              <div className="flex items-center justify-between">
                <span className="vx-mono text-[11px] font-semibold text-white">{analysis.symbol}</span>
                {unavailableSymbols?.has(analysis.symbol) ? (
                  <span className="rounded border border-[#59412a] bg-[#302318] px-1.5 py-0.5 text-[11px] text-[#f8bc63]">{t.dataUnavailable}</span>
                ) : (
                  <span className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[12px] font-semibold ${badge.bg} ${badge.text} border ${badge.border}`}>
                    <Icon className="h-2.5 w-2.5" />{recLabel(analysis.recommendation, t)}
                  </span>
                )}
              </div>
              {!unavailableSymbols?.has(analysis.symbol) && <div className="mt-1.5 flex items-center gap-2">
                <div className="h-1.5 flex-1 rounded-full bg-[#152a3d]">
                  <div className={`h-1.5 rounded-full ${badge.text.replace('text-', 'bg-')}`} style={{ width: `${analysis.probability_percent}%` }} />
                </div>
                <span className={`vx-mono text-[11px] ${badge.text}`}>{analysis.probability_percent}%</span>
              </div>}
              {analysis.override_reason && !unavailableSymbols?.has(analysis.symbol) && (
                <div className="mt-1 flex items-center gap-1 text-[12px] text-[#ffb24a]">
                  <ShieldAlert className="h-2.5 w-2.5" />{t.overrideActive}
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function TradeDeskDetail({ analysis, unavailable = false, t }: { analysis: TradeAnalysis | null; unavailable?: boolean; t: Dictionary }) {
  if (unavailable) {
    return <div className="vx-panel flex min-h-[260px] items-center justify-center p-6 text-center text-[12px] text-[#f8bc63]">{t.noMarketData}</div>;
  }
  if (!analysis) {
    return (
      <div className="vx-panel flex h-full min-h-[380px] items-center justify-center rounded-lg p-6 text-center text-[12px] text-[#5f7589]">
        {t.selectSymbolForAnalysis}
      </div>
    );
  }

  const badge = recBadge(analysis.recommendation);
  const Icon = badge.icon;
  const risk = riskColor(analysis.risk_label || 'LOW');
  const plan = analysis.recommendation === 'WAIT' ? null : analysis.entry_plan;

  return (
    <div className="vx-panel flex h-full flex-col gap-3 rounded-lg p-3.5">
      <div className="flex items-center justify-between">
        <div>
          <div className="vx-mono text-[13px] font-semibold text-white">{analysis.symbol}</div>
          <div className="text-[12px] text-[#6f8498]">{analysis.asset_class}</div>
        </div>
        <span className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-bold ${badge.bg} ${badge.text} border ${badge.border}`}>
          <Icon className="h-4 w-4" />{recLabel(analysis.recommendation, t)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <div className="rounded-md border border-[#15293c] bg-[#081522] p-2.5">
          <div className="text-[12px] text-[#71869b]">{t.probability}</div>
          <div className={`vx-mono mt-1 text-[16px] font-semibold ${badge.text}`}>{analysis.probability_percent}%</div>
        </div>
        <div className="rounded-md border border-[#15293c] bg-[#081522] p-2.5">
          <div className="text-[12px] text-[#71869b]">{t.suggestedRisk}</div>
          <div className="vx-mono mt-1 text-[16px] font-semibold text-white">
            {analysis.suggested_risk_percent > 0 ? `${analysis.suggested_risk_percent}%` : '—'}
          </div>
          <div className="text-[12px] text-[#5f7589]">{t.ofAccount}</div>
        </div>
        <div className="rounded-md border border-[#15293c] bg-[#081522] p-2.5">
          <div className="text-[12px] text-[#71869b]">{t.risk}</div>
          <div className={`mt-1 text-[13px] font-semibold ${risk.text}`}>{analysis.risk_label} · {analysis.risk_score}</div>
        </div>
      </div>

      {analysis.override_reason && (
        <div className="flex items-start gap-2 rounded-md border border-[#5c421a] bg-[#3a2a10] p-2.5 text-[11px] text-[#ffb24a]">
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{analysis.risk_label === 'HIGH' ? t.riskOverrideHigh : t.riskOverrideOther}</span>
        </div>
      )}

      {plan && (
        <div className="rounded-md border border-[#15293c] bg-[#081522] p-2.5">
          <div className="mb-1.5 flex items-center justify-between text-[11px]">
            <span className="text-[#c3d2df]">{t.entryPlan}</span>
            <span className="rounded bg-[#132330] px-1.5 py-0.5 text-[12px] text-[#8ca1b5]">
              {plan.basis === 'STRUCTURAL_TRIGGER' ? t.structuralTrigger : t.atrGeneric}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-[11px]">
            <div><div className="text-[#71869b]">{t.entry}</div><div className="vx-mono mt-0.5 text-white">{formatPrice(plan.entry, analysis.symbol)}</div></div>
            <div><div className="text-[#71869b]">{t.stopLoss}</div><div className="vx-mono mt-0.5 text-[#ff5a72]">{formatPrice(plan.sl, analysis.symbol)}</div></div>
            <div><div className="text-[#71869b]">{t.takeProfit}</div><div className="vx-mono mt-0.5 text-[#2ae9bd]">{formatPrice(plan.tp, analysis.symbol)}</div></div>
          </div>
          <p className="mt-2 text-[12px] leading-4 text-[#8598aa]">{plan.note}</p>
        </div>
      )}

      <div>
        <div className="mb-1.5 text-[11px] font-semibold text-[#c3d2df]">{t.methodBreakdown}</div>
        <div className="space-y-2">
          {analysis.method_breakdown.map((method) => {
            const leanColor = method.lean > 0.15 ? 'bg-[#2ae9bd]' : method.lean < -0.15 ? 'bg-[#ff5a72]' : 'bg-[#5f7589]';
            return (
              <div key={method.method} className="rounded-md border border-[#15293c] bg-[#081522] p-2">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-medium text-[#d7e2ec]">{method.method}</span>
                  <span className="text-[12px] text-[#5f7589]">{t.weight} {method.weight_percent}% · {t.confidence} {method.confidence_percent}%</span>
                </div>
                <div className="mt-1.5 h-1 rounded-full bg-[#152a3d]">
                  <div className={`h-1 rounded-full ${leanColor}`} style={{ width: `${Math.abs(method.lean) * 100}%`, marginLeft: method.lean < 0 ? 'auto' : undefined }} />
                </div>
                <p className="mt-1.5 text-[12px] leading-4 text-[#8598aa]">{method.detail}</p>
              </div>
            );
          })}
        </div>
      </div>

      <p className="border-t border-[#15293c] pt-2 text-[12px] leading-4 text-[#5f7589]">{t.analystDisclaimer}</p>
    </div>
  );
}

export function TradeCallHistory({ calls, t }: { calls: TradeCall[]; t: Dictionary }) {
  return (
    <div className="vx-panel rounded-lg p-3">
      <h3 className="mb-2 text-[12px] font-semibold text-white">{t.tradeCallHistory}</h3>
      <div className="vx-thin-scroll max-h-[220px] overflow-y-auto">
        <table className="w-full border-collapse text-left text-[11px] rtl:text-right">
          <thead>
            <tr className="border-b border-[#132b40] text-[#72879b]">
              <th className="py-1.5 pr-2">{t.symbol}</th>
              <th className="py-1.5 pr-2">{t.recommendation}</th>
              <th className="py-1.5 pr-2">{t.probability}</th>
              <th className="py-1.5 pr-2">{t.suggestedRisk}</th>
              <th className="py-1.5 pr-2">{t.entry}</th>
              <th className="py-1.5 pr-2">{t.time}</th>
            </tr>
          </thead>
          <tbody>
            {calls.length === 0 && (
              <tr><td colSpan={6} className="py-6 text-center text-[12px] text-[#5f7589]">{t.noTradeCalls}</td></tr>
            )}
            {calls.map((call) => (
              <tr key={call.id} className="border-b border-[#0f2233]">
                <td className="vx-mono py-1.5 pr-2 text-white">{call.symbol}</td>
                <td className={`py-1.5 pr-2 font-semibold ${call.recommendation === 'SELL' ? 'text-[#ff5a72]' : 'text-[#2ae9bd]'}`}>{call.recommendation}</td>
                <td className="vx-mono py-1.5 pr-2 text-[#c3d2df]">{call.probability_percent}%</td>
                <td className="vx-mono py-1.5 pr-2 text-[#c3d2df]">{call.suggested_risk_percent}%</td>
                <td className="vx-mono py-1.5 pr-2 text-[#c3d2df]">{formatPrice(call.entry, call.symbol)}</td>
                <td className="vx-mono py-1.5 pr-2 text-[#5f7589]">{new Date(call.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
