export type Priority = "high" | "medium" | "low";

export interface FeedItem {
  id: number;
  symbol: string;
  company_name: string;
  published_at: string;
  category: string | null;
  priority: Priority | null;
  materiality: number | null;
  headline: string;
  one_liner: string | null;
  exchange_category: string | null;
  attachment_url: string | null;
  enrichment: Record<string, any> | null;
  network: { for: string | null; results: Suggestion[] }[] | null;
}

export interface SignalItem {
  id: number;
  symbol: string;
  company_name: string;
  kind: "volume_spike" | "price_move" | string;
  priority: Priority;
  trade_date: string | null;
  title: string;
  body: string | null;
  payload: Record<string, any> | null;
}

export interface Feed {
  since: string;
  until: string;
  requested_hours: number;
  note: string | null;
  counts: { total: number; material: number; routine: number; signals: number };
  signals: SignalItem[];
  material: FeedItem[];
  routine: { category: string | null; count: number; items: FeedItem[] }[];
}

export interface AlertRule {
  id: number;
  rule_type: "volume_spike" | "price_move" | "announcement_category";
  company_id: number | null;
  params: Record<string, any>;
  enabled: boolean;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `${r.status} ${r.statusText}`);
  }
  return r.json();
}

export const api = {
  feed: (hours: number) => req<Feed>(`/feed?hours=${hours}`),
  rules: () => req<AlertRule[]>("/alert-rules"),
  saveRule: (id: number, params: Record<string, unknown>, enabled = true) =>
    req<AlertRule>(`/alert-rules/${id}`, { method: "PUT", body: JSON.stringify({ params, enabled }) }),
};

export const CATEGORY_LABEL: Record<string, string> = {
  results: "Results",
  m_and_a: "M&A",
  fund_raise: "Fund raise",
  management_change: "Management",
  litigation: "Litigation",
  insider_trading: "Insider trade",
  earnings_call: "Earnings call",
  investor_meetings: "Investor meets",
  credit_rating: "Credit rating",
  dividend: "Dividend",
  bonus_split: "Bonus / split",
  capex: "Capex",
  press_release: "Press release",
  postal_ballot: "Postal ballot",
  agm_egm: "AGM / EGM",
  pledging: "Pledging",
  unclassified: "Routine paperwork",
};

// ---------- Network ----------
export interface Suggestion {
  person_id: number;
  name: string;
  headline: string | null;
  relationship: string | null;
  strength: number | null;
  last_spoke_days: number | null;
  score: number;
  reasons: string[];
  caution: string | null;
  via: { person_id: number; name: string; relationship: string; link_strength: number; evidence: string }[] | null;
}

export interface KeepWarm {
  person_id: number;
  name: string;
  headline: string | null;
  relationship: string;
  strength: number;
  last_spoke_days: number;
  hook: string;
  symbol: string;
  category: string | null;
}

export interface PersonCard {
  id: number;
  name: string;
  headline: string | null;
  location: string | null;
  source: string;
  relationship: string | null;
  strength: number | null;
  last_spoke_days: number | null;
  how_met: string | null;
  experiences: { org: string; title: string; years: string; symbol: string | null }[];
  educations: { institution: string; degree: string; years: string }[];
  expertise: string[];
  path: Suggestion["via"];
}

// ---------- Pull ----------
export interface ResultsCompare {
  label: string;
  prev_label: string | null;
  yago_label: string | null;
  rows: { metric: string; value: number | null; qoq: number | null; yoy: number | null }[];
  ebitda_margin: number | null;
  ebitda_margin_prev: number | null;
  ebitda_margin_yago: number | null;
  checks: string[];
  consolidated: boolean;
  source: string;
}

export interface Promise_ {
  said_in: string;
  metric: string;
  guided: string;
  target: string;
  quote: string;
  page: number | null;
  actual: number | null;
  status: "met" | "partial" | "missed" | "pending" | "withdrawn";
  assessment: string;
  detail: string | null;
  span: string | null;
  source_url: string | null;
}

export interface Research {
  symbol: string;
  name: string;
  sector: string | null;
  industry: string | null;
  market_cap_cr: number | null;
  description: string | null;
  is_lender: boolean;
  ratios: Record<string, number | null>;
  latest: ResultsCompare | null;
  ttm: { revenue: number; pat: number; revenue_growth: number | null; pat_growth: number | null; ebitda_margin: number | null } | null;
  trajectory: {
    years: { label: string; revenue: number | null; ebitda_margin: number | null; pat: number | null; cfo: number | null; roce: number | null }[];
    revenue_cagr_3y?: number | null;
    pat_cagr_3y?: number | null;
    margin_change_3y_pts?: number | null;
  };
  balance: { borrowings: number | null; equity: number | null; debt_to_equity: number | null; ccc_days: number | null; ccc_days_3y_ago: number | null; label: string } | null;
  cash: { cfo_5y: number; pat_5y: number; fcf_5y: number; cfo_to_pat: number | null; cfo_to_ebitda: number | null; years: number } | null;
  narrative: Promise_[];
  signals: { bull: string[]; bear: string[] };
  who_to_call: Suggestion[];
  sources: { type: string; title: string; period: string | null; url: string; date: string | null; used: boolean }[];
  grounding: string;
}

export type AskResult =
  | { type: "who_to_call"; title: string; symbol: string; results: Suggestion[] }
  | { type: "expertise"; title: string; results: Suggestion[] }
  | { type: "keep_warm"; title: string; results: KeepWarm[] }
  | { type: "person_reach"; title: string; person: any; results: Suggestion[] }
  | { type: "person"; title: string; person: PersonCard }
  | { type: "company"; title: string; symbol: string }
  | { type: "help"; title: string; examples: string[] };

export const net = {
  research: (s: string) => req<Research>(`/research/${encodeURIComponent(s)}`),
  ask: (q: string) => req<AskResult>("/ask", { method: "POST", body: JSON.stringify({ q }) }),
  keepWarm: () => req<KeepWarm[]>("/network/keep-warm"),
  themes: () => req<{ theme: string; people: number }[]>("/network/themes"),
  expertise: (q: string) => req<Suggestion[]>(`/network/expertise?q=${encodeURIComponent(q)}`),
  person: (id: number) => req<PersonCard>(`/network/people/${id}`),
};
