import { useEffect, useState } from "react";
import { net, type Promise_, type Research } from "../api";
import { crore, Delta, PersonRow, Section, SyntheticNote } from "../components";
import { go } from "../nav";
import { ResultsTable } from "./ResultsTable";

const METRIC: Record<string, string> = {
  revenue_growth: "Revenue growth",
  ebitda_margin: "EBITDA margin",
  capex: "Capex",
};

const STATUS: Record<Promise_["status"], { label: string; cls: string }> = {
  met: { label: "Delivered", cls: "text-up border-up/40" },
  partial: { label: "On track", cls: "text-up border-up/30" },
  missed: { label: "Behind", cls: "text-down border-down/40" },
  pending: { label: "Can't check yet", cls: "text-mute border-line" },
  withdrawn: { label: "Withdrawn", cls: "text-mute border-line" },
};

export default function Company({ symbol }: { symbol: string }) {
  const [r, setR] = useState<Research | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    setR(null);
    setErr(null);
    const t = setTimeout(() => setSlow(true), 2500);
    net.research(symbol).then(setR).catch((e) => setErr(e.message)).finally(() => clearTimeout(t));
    return () => clearTimeout(t);
  }, [symbol]);

  return (
    <div className="pb-24">
      <header className="sticky top-0 z-10 bg-bg/90 backdrop-blur border-b border-line px-4 py-3 flex items-center gap-3">
        <button onClick={() => history.back()} className="text-mute text-lg leading-none" aria-label="Back">
          ←
        </button>
        <div className="min-w-0">
          <div className="font-semibold leading-tight">{symbol}</div>
          <div className="text-xs text-mute truncate">{r ? `${r.name} · ${r.industry ?? r.sector ?? ""}` : "Research"}</div>
        </div>
      </header>

      {!r && !err && (
        <div className="p-6 text-sm text-mute">
          Reading {symbol}'s filings…
          {slow && (
            <div className="mt-2 text-xs">
              First look at this company: fetching its financials and last four earnings-call transcripts. This takes
              a few seconds once, then it's cached.
            </div>
          )}
        </div>
      )}
      {err && <div className="m-4 p-3 rounded-lg border border-down/40 text-down text-sm">{err}</div>}
      {r && <Body r={r} />}
    </div>
  );
}

function Body({ r }: { r: Research }) {
  const t = r.trajectory;
  return (
    <main className="px-4">
      {/* Snapshot */}
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <Stat label="Market cap" value={crore(r.market_cap_cr)} />
        <Stat label="P/E" value={r.ratios.stock_p_e?.toFixed(1) ?? "—"} />
        <Stat label={r.is_lender ? "ROE" : "ROCE"} value={`${(r.is_lender ? r.ratios.roe : r.ratios.roce)?.toFixed(1) ?? "—"}%`} />
      </div>
      {r.description && <p className="mt-3 text-[13px] text-mute leading-relaxed line-clamp-4">{r.description}</p>}

      {/* What the numbers say: the tightest bull/bear */}
      {(r.signals.bull.length > 0 || r.signals.bear.length > 0) && (
        <Section title="What the numbers say">
          <div className="grid grid-cols-1 gap-2">
            {r.signals.bear.length > 0 && <SignalList tone="bear" items={r.signals.bear} />}
            {r.signals.bull.length > 0 && <SignalList tone="bull" items={r.signals.bull} />}
          </div>
        </Section>
      )}

      {/* Narrative vs numbers */}
      <Section title="Promised vs delivered" hint="last 4 earnings calls">
        {r.narrative.length === 0 ? (
          <p className="text-sm text-mute">No explicit numeric guidance found in the last four transcripts.</p>
        ) : (
          <ul className="space-y-2">
            {r.narrative
              .slice()
              .sort((a, b) => rank(a) - rank(b))
              .slice(0, 6)
              .map((p, i) => (
                <PromiseCard key={i} p={p} />
              ))}
          </ul>
        )}
        <p className="text-[11px] text-mute mt-2">
          Promises are quoted verbatim from transcripts (page cited); "delivered" is computed from reported quarters.
        </p>
      </Section>

      {/* Latest quarter */}
      {r.latest && (
        <Section title={`Latest quarter · ${r.latest.label}`} hint={r.latest.consolidated ? "consolidated" : "standalone"}>
          <ResultsTable c={r.latest} lender={r.is_lender} />
        </Section>
      )}

      {/* Trajectory */}
      {t.years.length > 0 && (
        <Section
          title="Trajectory"
          hint={t.revenue_cagr_3y != null ? `3-yr revenue CAGR ${t.revenue_cagr_3y.toFixed(0)}%` : undefined}
        >
          <Bars years={t.years} lender={r.is_lender} />
          <div className="mt-2 flex gap-4 text-xs text-mute">
            {t.pat_cagr_3y != null && <span>PAT CAGR {t.pat_cagr_3y.toFixed(0)}%</span>}
            {t.margin_change_3y_pts != null && !r.is_lender && (
              <span>
                Margin <Delta v={t.margin_change_3y_pts} suffix=" pts" /> in 3 yrs
              </span>
            )}
          </div>
        </Section>
      )}

      {/* Balance sheet + cash */}
      {!r.is_lender && (r.balance || r.cash) && (
        <Section title="Balance sheet & cash" hint={r.balance?.label}>
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Debt / equity" value={r.balance?.debt_to_equity?.toFixed(2) ?? "—"} />
            <Stat
              label="Cash cycle"
              value={r.balance?.ccc_days != null ? `${r.balance.ccc_days.toFixed(0)} days` : "—"}
              sub={r.balance?.ccc_days_3y_ago != null ? `${r.balance.ccc_days_3y_ago.toFixed(0)} days 3 yrs ago` : undefined}
            />
            <Stat
              label={`CFO / EBITDA (${r.cash?.years ?? 0} yrs)`}
              value={r.cash?.cfo_to_ebitda != null ? `${r.cash.cfo_to_ebitda}%` : "—"}
              sub="share of operating profit that became cash"
            />
            <Stat label="Free cash flow (5 yrs)" value={crore(r.cash?.fcf_5y)} />
          </div>
        </Section>
      )}

      {/* Network */}
      <Section title="Who to call">
        {r.who_to_call.length === 0 ? (
          <p className="text-sm text-mute">Nobody in your network has a direct line here yet.</p>
        ) : (
          <div className="divide-y divide-line">
            {r.who_to_call.map((s) => (
              <PersonRow key={s.person_id} s={s} />
            ))}
          </div>
        )}
        <SyntheticNote />
      </Section>

      {/* Sources */}
      <Section title="Sources">
        <ul className="text-[13px] space-y-1">
          {r.sources.map((s) => (
            <li key={s.url} className="flex justify-between gap-3">
              <a href={s.url} target="_blank" rel="noreferrer" className="underline underline-offset-2 truncate">
                {s.title} {s.period ? `· ${s.period}` : ""}
              </a>
              {s.used && <span className="text-[11px] text-mute shrink-0">read</span>}
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-mute mt-2">{r.grounding}</p>
      </Section>
    </main>
  );
}

function rank(p: Promise_) {
  return { missed: 0, partial: 1, met: 2, pending: 3, withdrawn: 4 }[p.status];
}

function PromiseCard({ p }: { p: Promise_ }) {
  const st = STATUS[p.status];
  return (
    <li className="rounded-xl border border-line bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[13px] font-medium">
          {METRIC[p.metric] ?? p.metric} <span className="text-mute font-normal">· said {p.said_in}, for {p.target}</span>
        </div>
        <span className={`text-[11px] px-2 h-6 inline-flex items-center rounded-full border ${st.cls}`}>{st.label}</span>
      </div>
      <blockquote className="mt-1.5 text-[13px] leading-snug border-l-2 border-line pl-2.5 text-ink/90">
        “{p.quote.length > 260 ? p.quote.slice(0, 257) + "…" : p.quote}”
        {p.source_url && (
          <a href={p.source_url} target="_blank" rel="noreferrer" className="text-mute text-[11px] ml-1 underline">
            p.{p.page}
          </a>
        )}
      </blockquote>
      <div className="mt-1.5 text-[13px] flex flex-wrap gap-x-3">
        <span>
          Guided <b className="num">{p.guided}</b>
        </span>
        {p.actual != null && (
          <span>
            Delivered <b className="num">{p.actual.toFixed(1)}%</b> <span className="text-mute">({p.span})</span>
          </span>
        )}
      </div>
      <div className="text-[11px] text-mute mt-0.5">{p.assessment}</div>
    </li>
  );
}

function SignalList({ tone, items }: { tone: "bull" | "bear"; items: string[] }) {
  return (
    <div className={`rounded-xl border p-3 ${tone === "bear" ? "border-down/30" : "border-up/30"}`}>
      <div className={`text-[11px] uppercase tracking-wider font-semibold ${tone === "bear" ? "text-down" : "text-up"}`}>
        {tone === "bear" ? "Bear case" : "Bull case"}
      </div>
      <ul className="mt-1 space-y-1 text-[13px] leading-snug">
        {items.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl bg-card border border-line px-2.5 py-2 text-left">
      <div className="text-[11px] text-mute">{label}</div>
      <div className="num font-semibold">{value}</div>
      {sub && <div className="text-[10px] text-mute leading-tight mt-0.5">{sub}</div>}
    </div>
  );
}

function Bars({ years, lender }: { years: Research["trajectory"]["years"]; lender: boolean }) {
  const max = Math.max(...years.map((y) => y.revenue ?? 0), 1);
  return (
    <div className="flex items-end gap-1.5 h-32">
      {years.map((y) => (
        <div key={y.label} className="flex-1 flex flex-col items-center justify-end h-full">
          {!lender && y.ebitda_margin != null && (
            <div className="text-[10px] num text-accent mb-0.5">{y.ebitda_margin.toFixed(0)}%</div>
          )}
          <div className="w-full rounded-t bg-ink/80" style={{ height: `${((y.revenue ?? 0) / max) * 75}%` }} />
          <div className="text-[10px] text-mute mt-1 num">{y.label}</div>
        </div>
      ))}
    </div>
  );
}

export function openCompany(symbol: string) {
  go({ company: symbol });
}
