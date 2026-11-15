import type { ReactNode } from "react";
import type { Suggestion } from "./api";
import { go } from "./nav";

const REL: Record<string, string> = {
  classmate: "Classmate",
  colleague: "Ex-colleague",
  friend: "Friend",
  met_management: "Met in diligence",
  industry: "Industry contact",
  family: "Family",
  other: "Contact",
};

export function relLabel(r: string | null) {
  return r ? REL[r] ?? r : "Not a contact";
}

export function lastSpoke(days: number | null) {
  if (days === null || days === undefined) return null;
  if (days < 30) return "spoke recently";
  if (days < 365) return `last spoke ${Math.round(days / 30)} mo ago`;
  return `last spoke ${(days / 365).toFixed(1)} yr ago`;
}

export function Strength({ n }: { n: number | null }) {
  if (!n) return null;
  return (
    <span className="inline-flex gap-[2px] align-middle" aria-label={`closeness ${n} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span key={i} className={`w-1 h-2.5 rounded-sm ${i <= n ? "bg-accent" : "bg-line"}`} />
      ))}
    </span>
  );
}

/** A person the investor could call, and why. The "why" is the product. */
export function PersonRow({ s, compact = false }: { s: Suggestion; compact?: boolean }) {
  const direct = s.relationship !== null;
  return (
    <button onClick={() => go({ person: s.person_id })} className="w-full text-left py-2 flex gap-2.5 items-start">
      <Avatar name={s.name} dim={!direct} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-[14px]">{s.name}</span>
          {direct ? (
            <span className="text-[11px] text-mute">
              {relLabel(s.relationship)} <Strength n={s.strength} />
            </span>
          ) : (
            s.via && <span className="text-[11px] text-accent">via {s.via[0].name}</span>
          )}
        </div>
        {!compact && s.headline && <div className="text-xs text-mute truncate">{s.headline}</div>}
        <ul className="mt-0.5 text-[13px] leading-snug">
          {s.reasons.slice(0, compact ? 1 : 3).map((r, i) => (
            <li key={i} className="text-ink/90">
              {r}
            </li>
          ))}
        </ul>
        {!direct && s.via && !compact && (
          <div className="text-xs text-mute mt-0.5">Intro path: {s.via[0].evidence}</div>
        )}
        {s.caution && <div className="text-[11px] text-accent mt-0.5">⚠ {s.caution}</div>}
      </div>
    </button>
  );
}

export function Avatar({ name, dim = false }: { name: string; dim?: boolean }) {
  const initials = name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("");
  return (
    <span
      className={`shrink-0 w-8 h-8 rounded-full grid place-items-center text-[11px] font-semibold ${
        dim ? "border border-dashed border-line text-mute" : "bg-line text-ink"
      }`}
    >
      {initials}
    </span>
  );
}

export function Delta({ v, suffix = "%" }: { v: number | null | undefined; suffix?: string }) {
  if (v === null || v === undefined || Number.isNaN(v)) return <span className="text-mute">—</span>;
  const tone = v > 0.05 ? "text-up" : v < -0.05 ? "text-down" : "text-mute";
  return (
    <span className={`num ${tone}`}>
      {v > 0 ? "+" : ""}
      {v.toFixed(1)}
      {suffix}
    </span>
  );
}

export function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="mt-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-[11px] uppercase tracking-[0.14em] text-mute font-semibold">{title}</h2>
        {hint && <span className="text-[11px] text-mute">{hint}</span>}
      </div>
      <div className="mt-2">{children}</div>
    </section>
  );
}

export function crore(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 100000) return `₹${(v / 100000).toFixed(2)} L cr`;
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} cr`;
}

export function SyntheticNote() {
  return (
    <p className="text-[11px] text-mute mt-2">
      Network data is synthetic for this demo. Links to real executives are inferred from their exchange filings.
    </p>
  );
}
