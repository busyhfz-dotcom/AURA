export type AssetClass = 'CRYPTO' | 'FOREX' | 'METALS' | 'UNKNOWN';
export type SignalStatus = 'A_PLUS_SETUP' | 'SCANNING' | 'WAITING_FOR_DATA';
export type RiskLabel = 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH';

export type Checklist = {
  sweep: boolean;
  displacement: boolean;
  fvg_midpoint: boolean;
  killzone_active: boolean;
  session_name?: string;
};

export type Signal = {
  symbol: string;
  status: SignalStatus;
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

export type Risk = {
  symbol: string;
  asset_class: AssetClass;
  risk_score: number;
  risk_label: RiskLabel;
  volatility_percent: number | null;
  volatility_state: 'LOW' | 'NORMAL' | 'ELEVATED' | 'UNAVAILABLE' | string;
  news_embargo_active: boolean;
  killzone_active: boolean;
  change_percent_24h: number | null;
  reasons: string[];
};

export type Snapshot = {
  symbol: string;
  last_price: number;
  price_change: number;
  price_change_percent: number;
  high_24h: number;
  low_24h: number;
  volume_24h?: number;
  quote_volume_24h?: number;
  trades_24h?: number;
} | null;

export type MarketRecord = {
  symbol: string;
  asset_class: AssetClass;
  source: string;
  data_available: boolean;
  snapshot: Snapshot;
  signal: Signal;
  risk: Risk;
  news_guard: { configured: boolean; active: boolean; safe?: boolean; provider_error?: string | null; message?: string };
  updated_at: number;
};

export type AlertItem = {
  id: string;
  symbol: string;
  asset_class: AssetClass;
  category: 'RISK' | 'NEWS' | 'SETUP' | string;
  severity: 'HIGH' | 'MEDIUM' | 'INFO' | string;
  title: string;
  message: string;
  created_at: string;
};

export type SignalEvent = {
  id: string;
  symbol: string;
  asset_class: AssetClass;
  status: string;
  action?: string;
  entry?: number;
  sl?: number;
  tp?: number;
  confluence_score: number;
  session?: string;
  created_at: string;
};

export type Stats24h = {
  window_hours: number;
  total_scans: number;
  entries_detected: number;
  alerts_by_severity: Record<string, number>;
  signals_by_status: Record<string, number>;
  avg_risk_by_asset_class: Record<string, { avg_score: number; max_score: number; samples: number }>;
  top_risk_symbols: { symbol: string; asset_class: string; peak_score: number }[];
};

export type CalendarEvent = {
  event: string;
  country: string | null;
  currency: string | null;
  time: string;
  impact: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN';
  actual?: unknown;
  estimate?: unknown;
  previous?: unknown;
};

export type MethodBreakdownItem = {
  method: string;
  weight_percent: number;
  lean: number;
  confidence_percent: number;
  detail: string;
};

export type EntryPlan = {
  basis: 'STRUCTURAL_TRIGGER' | 'ATR_GENERIC';
  entry: number;
  sl: number;
  tp: number;
  rr: string;
  note: string;
} | null;

export type TradeAnalysis = {
  symbol: string;
  asset_class: AssetClass;
  recommendation: 'BUY' | 'SELL' | 'WAIT';
  raw_recommendation: 'BUY' | 'SELL' | 'WAIT';
  probability_percent: number;
  composite_bullish_percent: number;
  composite_bearish_percent: number;
  override_reason: string | null;
  entry_plan: EntryPlan;
  suggested_risk_percent: number;
  risk_label: RiskLabel;
  risk_score: number;
  method_breakdown: MethodBreakdownItem[];
  reasons: string[];
  disclaimer: string;
  updated_at: number;
};

export type TradeCall = {
  id: string;
  symbol: string;
  asset_class: AssetClass;
  recommendation: string;
  probability_percent: number;
  suggested_risk_percent: number;
  entry: number | null;
  sl: number | null;
  tp: number | null;
  basis: string | null;
  created_at: string;
};

export type HealthPayload = {
  status: string;
  brand: string;
  version: string;
  uptime_seconds: number;
  scan_count: number;
  scan_counts_by_class?: { crypto: number; forex: number };
  scan_interval_seconds: number;
  data_status: {
    crypto: { provider: string; healthy: boolean; last_error: string | null };
    forex: { configured: boolean; provider: string | null; message?: string; healthy?: boolean; last_error?: string | null };
  };
  news_guard: { configured: boolean; active: boolean; safe?: boolean; provider_error?: string | null; message?: string };
  telegram_configured: boolean;
  disclaimer: string;
};
