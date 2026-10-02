import React, { useEffect, useRef } from 'react';
import { createChart, IChartApi, ISeriesApi } from 'lightweight-charts';
import type { Dictionary } from '../locales/dictionary';
import type { MarketRecord } from './types';
import { formatPct, formatPrice, riskColor } from './panels';

type Candle = { time: number; open: number; high: number; low: number; close: number };

export default function SymbolDetail({
  record, candles, t,
}: { record: MarketRecord | null; candles: Candle[]; t: Dictionary }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const priceLinesRef = useRef<any[]>([]);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      width: ref.current.clientWidth,
      height: ref.current.clientHeight,
      layout: { background: { color: 'transparent' }, textColor: '#70859b', fontSize: 10 },
      grid: { vertLines: { color: 'rgba(68,108,143,.1)' }, horzLines: { color: 'rgba(68,108,143,.1)' } },
      rightPriceScale: { borderColor: 'rgba(73,113,148,.19)' },
      timeScale: { borderColor: 'rgba(73,113,148,.19)', timeVisible: true, secondsVisible: false },
    });
    const series = chart.addCandlestickSeries({
      upColor: '#16d9b0', downColor: '#ef4966', borderUpColor: '#16d9b0', borderDownColor: '#ef4966',
      wickUpColor: '#1ce2b9', wickDownColor: '#ff5b75',
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
    for (const line of priceLinesRef.current) { try { series.removePriceLine(line); } catch { /* noop */ } }
    priceLinesRef.current = [];
    const signal = record?.signal;
    if (!signal || signal.status !== 'A_PLUS_SETUP' || !signal.entry || !signal.sl || !signal.tp) return;
    priceLinesRef.current = [
      series.createPriceLine({ price: signal.entry, color: '#2e93ff', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'ENTRY' }),
      series.createPriceLine({ price: signal.sl, color: '#ff5a72', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SL' }),
      series.createPriceLine({ price: signal.tp, color: '#2ae9bd', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TP' }),
    ];
  }, [record]);

  if (!record) {
    return (
      <div className="vx-panel flex h-full min-h-[380px] items-center justify-center rounded-lg text-[10px] text-[#5f7589]">
        {t.search}
      </div>
    );
  }

  const risk = riskColor(record.risk?.risk_label || 'LOW');
  const signal = record.signal;
  const ready = signal?.status === 'A_PLUS_SETUP';

  return (
    <div className="vx-panel flex h-full flex-col rounded-lg">
      <div className="flex items-center justify-between border-b border-[#15293c] px-3 py-2.5">
        <div>
          <div className="vx-mono text-[13px] font-semibold text-white">{record.symbol}</div>
          <div className="text-[8px] text-[#6f8498]">{record.asset_class} · {record.source}</div>
        </div>
        <div className="text-right rtl:text-left">
          <div className="vx-mono text-[14px] font-semibold text-white">{formatPrice(record.snapshot?.last_price, record.symbol)}</div>
          <div className={`vx-mono text-[9px] ${(record.snapshot?.price_change_percent ?? 0) >= 0 ? 'text-[#2ae9bd]' : 'text-[#ff5a72]'}`}>
            {formatPct(record.snapshot?.price_change_percent ?? record.risk?.change_percent_24h)}
          </div>
        </div>
      </div>

      <div className="h-[260px] shrink-0 px-1 pt-1"><div ref={ref} className="h-full w-full" /></div>

      <div className="grid grid-cols-2 gap-2 border-t border-[#15293c] p-3 sm:grid-cols-4">
        <div className="rounded-md border border-[#15293c] bg-[#081522] p-2">
          <div className="text-[8px] text-[#71869b]">{t.risk}</div>
          <div className={`vx-mono mt-1 text-[13px] font-semibold ${risk.text}`}>{record.risk?.risk_score ?? 0}/100</div>
        </div>
        <div className="rounded-md border border-[#15293c] bg-[#081522] p-2">
          <div className="text-[8px] text-[#71869b]">{t.volatility}</div>
          <div className="mt-1 text-[11px] text-white">{record.risk?.volatility_state || '—'}</div>
        </div>
        <div className="rounded-md border border-[#15293c] bg-[#081522] p-2">
          <div className="text-[8px] text-[#71869b]">{t.session}</div>
          <div className="mt-1 text-[11px] text-white">{signal?.checklist?.session_name || signal?.session || '—'}</div>
        </div>
        <div className="rounded-md border border-[#15293c] bg-[#081522] p-2">
          <div className="text-[8px] text-[#71869b]">{t.status}</div>
          <div className="mt-1 text-[11px] text-white">
            {ready ? t.validated : signal?.status === 'SCANNING' ? t.scanning : t.waitingForData}
          </div>
        </div>
      </div>

      {ready && (
        <div className="border-t border-[#15293c] p-3">
          <div className="flex items-center justify-between">
            <span className={`text-[16px] font-bold ${signal!.action === 'SELL' ? 'text-[#ff5a72]' : 'text-[#2ae9bd]'}`}>{signal!.action}</span>
            <span className="vx-mono text-[11px] text-[#8ca1b5]">{t.confluence}: {signal!.confluence_score}/100</span>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-[9px]">
            <div><div className="text-[#71869b]">{t.entry}</div><div className="vx-mono mt-0.5 text-white">{formatPrice(signal!.entry, record.symbol)}</div></div>
            <div><div className="text-[#71869b]">{t.stopLoss}</div><div className="vx-mono mt-0.5 text-[#ff5a72]">{formatPrice(signal!.sl, record.symbol)}</div></div>
            <div><div className="text-[#71869b]">{t.takeProfit}</div><div className="vx-mono mt-0.5 text-[#2ae9bd]">{formatPrice(signal!.tp, record.symbol)}</div></div>
          </div>
        </div>
      )}

      {record.risk?.reasons?.length > 0 && (
        <div className="border-t border-[#15293c] p-3">
          <ul className="space-y-1 text-[9px] text-[#9aabba]">
            {record.risk.reasons.map((reason, i) => <li key={i}>• {reason}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
