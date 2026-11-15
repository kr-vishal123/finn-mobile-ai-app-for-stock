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
  enrichment: Record<string, unknown> | null;
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
