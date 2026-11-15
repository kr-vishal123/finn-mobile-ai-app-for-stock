import { useEffect, useMemo, useState } from "react";
import { api, CATEGORY_LABEL, type Feed, type FeedItem, type Priority, type SignalItem } from "../api";
import { ago, istTime, shortDay } from "../format";
import AlertSettings from "./AlertSettings";
import { ResultsTable } from "./ResultsTable";
import { PersonRow } from "../components";
import { go } from "../nav";

const WINDOWS = [
  { h: 24, label: "24h" },
  { h: 72, label: "3d" },
  { h: 168, label: "7d" },
  { h: 720, label: "30d" },
];

const RANK: Record<Priority, number> = { high: 0, medium: 1, low: 2 };

interface CompanyStory {
  symbol: string;
  name: string;
  top: Priority;
  score: number;
  latest: string;
  filings: FeedItem[];
  signals: SignalItem[];
}

/** One card per company: filings + market signals for the same name read as one story. */
function groupByCompany(feed: Feed): CompanyStory[] {
  const by = new Map<string, CompanyStory>();
  const get = (symbol: string, name: string) => {
    if (!by.has(symbol))
      by.set(symbol, { symbol, name, top: "low", score: 0, latest: "", filings: [], signals: [] });
    return by.get(symbol)!;
  };
  for (const f of feed.material) {
    const s = get(f.symbol, f.company_name);
    s.filings.push(f);
    s.score += f.materiality ?? 0;
    if (f.priority && RANK[f.priority] < RANK[s.top]) s.top = f.priority;
    if (f.published_at > s.latest) s.latest = f.published_at;
  }
  // A volume spike already shows that day's % move, so a same-day price alert is redundant.
  const spikeDays = new Set(
    feed.signals.filter((x) => x.kind === "volume_spike").map((x) => `${x.symbol}|${x.trade_date}`),
  );
  for (const sig of feed.signals) {
    const s = get(sig.symbol, sig.company_name);
    if (sig.kind === "price_move" && spikeDays.has(`${sig.symbol}|${sig.trade_date}`)) {
      // keep its severity, drop the duplicate chip
      if (RANK[sig.priority] < RANK[s.top]) s.top = sig.priority;
      continue;
    }
    s.signals.push(sig);
    s.score += sig.priority === "high" ? 4 : 3;
    if (RANK[sig.priority] < RANK[s.top]) s.top = sig.priority;
    const t = (sig.trade_date ?? "") + "T10:00:00Z";
    if (t > s.latest) s.latest = t;
  }
  // A results press release next to the statutory results filing is the same news twice.
  for (const s of by.values()) {
    const results = s.filings.filter((f) => f.category === "results");
    if (results.length > 1) {
      const statutory = results.find((f) => !/press release/i.test(f.exchange_category ?? ""));
      if (statutory) s.filings = s.filings.filter((f) => f.category !== "results" || f === statutory);
    }
  }
  return [...by.values()].sort(
    (a, b) => RANK[a.top] - RANK[b.top] || b.score - a.score || b.latest.localeCompare(a.latest),
  );
}

export default function Today() {
  const [hours, setHoursState] = useState(() => {
    const h = Number(new URLSearchParams(location.search).get("h"));
    return WINDOWS.some((w) => w.h === h) ? h : 24;
  });
  const setHours = (h: number) => {
    setHoursState(h);
    history.replaceState(null, "", (h === 24 ? location.pathname : `?h=${h}`) + location.hash);
  };
  const [feed, setFeed] = useState<Feed | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    api.feed(hours).then(setFeed).catch((e) => setErr(String(e.message ?? e))).finally(() => setLoading(false));
  }, [hours, reload]);

  const stories = useMemo(() => (feed ? groupByCompany(feed) : []), [feed]);

  return (
    <div className="pb-24">
      <header className="sticky top-0 z-10 bg-bg/90 backdrop-blur border-b border-line">
        <div className="px-4 pt-3 pb-2 flex items-center justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.14em] text-mute">
              Portfolio · {hours === 24 ? "last 24 hours" : `last ${WINDOWS.find((w) => w.h === hours)?.label ?? `${hours}h`}`}
            </div>
            <h1 className="text-lg font-semibold leading-tight">
              {feed ? <Headline feed={feed} stories={stories.length} /> : "Loading…"}
            </h1>
          </div>
          <button
            onClick={() => setSettingsOpen(true)}
            className="h-9 px-3 rounded-full border border-line text-sm text-mute hover:text-ink"
            aria-label="Alert thresholds"
          >
            Thresholds
          </button>
        </div>
        <div className="px-4 pb-3 flex gap-1.5">
          {WINDOWS.map((w) => (
            <button
              key={w.h}
              onClick={() => setHours(w.h)}
              className={`h-8 px-3.5 rounded-full text-sm num transition ${
                hours === w.h ? "bg-ink text-bg font-medium" : "text-mute border border-line"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </header>

      {err && <div className="m-4 p-3 rounded-lg border border-down/40 text-down text-sm">Couldn't load feed: {err}</div>}
      {feed?.note && (
        <div className="mx-4 mt-3 text-[13px] text-mute border-l-2 border-accent pl-2.5">{feed.note}</div>
      )}

      <main className={`px-4 mt-3 space-y-3 ${loading ? "opacity-50" : ""}`}>
        {feed && stories.length === 0 && (
          <div className="py-10 text-center text-mute text-sm">
            Nothing material in this window.
            <br />
            {feed.counts.routine} routine filing{feed.counts.routine === 1 ? "" : "s"} below.
          </div>
        )}
        {stories.map((s) => (
          <StoryCard key={s.symbol} story={s} />
        ))}
        {feed && feed.routine.length > 0 && <Routine groups={feed.routine} total={feed.counts.routine} />}
      </main>

      {settingsOpen && (
        <AlertSettings
          onClose={(changed) => {
            setSettingsOpen(false);
            if (changed) setReload((n) => n + 1);
          }}
        />
      )}
    </div>
  );
}

function Headline({ feed, stories }: { feed: Feed; stories: number }) {
  if (stories === 0) return <>All quiet</>;
  return (
    <>
      {stories} {stories === 1 ? "name needs" : "names need"} a look
      <span className="text-mute font-normal text-sm"> · {feed.counts.routine} routine hidden</span>
    </>
  );
}

function StoryCard({ story }: { story: CompanyStory }) {
  const high = story.top === "high";
  // One "who to call" per company, from its most material non-people filing (people get their own).
  const callList =
    story.filings.find((f) => f.category !== "management_change" && f.network?.length)?.network?.[0]?.results.slice(0, 2) ?? [];
  return (
    <article className={`rounded-xl bg-card border ${high ? "border-accent/50" : "border-line"} overflow-hidden`}>
      <div className="px-3.5 pt-3 flex items-baseline justify-between gap-2">
        <button onClick={() => go({ company: story.symbol })} className="min-w-0 text-left">
          <span className="font-semibold tracking-tight">{story.symbol}</span>
          <span className="text-mute text-xs ml-2 truncate">{story.name.replace(/ (Ltd|Limited)\.?$/, "")} ›</span>
        </button>
        {high && <span className="text-[10px] uppercase tracking-wider text-accent font-semibold">Material</span>}
      </div>

      {story.signals.length > 0 && (
        <div className="px-3.5 pt-2 flex flex-wrap gap-1.5">
          {story.signals.map((s) => (
            <SignalChip key={s.id} s={s} />
          ))}
        </div>
      )}

      <ul className="mt-1.5 divide-y divide-line">
        {story.filings.map((f) => (
          <FilingRow key={f.id} f={f} />
        ))}
      </ul>
      {callList.length > 0 && (
        <div className="mx-3.5 mb-3 rounded-lg bg-bg/60 border border-line px-2.5 py-1">
          <div className="text-[10px] uppercase tracking-wider text-accent font-semibold pt-1">Who to call about this</div>
          {callList.map((s) => (
            <PersonRow key={s.person_id} s={s} compact />
          ))}
        </div>
      )}
      {story.filings.length === 0 && <div className="h-3" />}
    </article>
  );
}

function SignalChip({ s }: { s: SignalItem }) {
  const p = s.payload ?? {};
  const move: number | undefined = p.pct_change;
  const main = s.kind === "volume_spike" ? `${Number(p.value).toFixed(1)}× volume` : `${move! > 0 ? "+" : ""}${move?.toFixed(1)}%`;
  const tone =
    s.kind === "price_move" ? (move! > 0 ? "text-up border-up/40" : "text-down border-down/40") : "text-accent border-accent/40";
  return (
    <span className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full border text-xs num ${tone}`} title={s.body ?? ""}>
      <span className="font-semibold">{main}</span>
      {s.kind === "volume_spike" && move !== undefined && move !== null && (
        <span className={move >= 0 ? "text-up" : "text-down"}>
          {move > 0 ? "+" : ""}
          {move.toFixed(1)}%
        </span>
      )}
      {s.trade_date && <span className="text-mute">{shortDay(s.trade_date)}</span>}
    </span>
  );
}

function FilingRow({ f }: { f: FeedItem }) {
  const text = f.one_liner || f.headline;
  const enr = f.enrichment ?? {};
  const people: any[] = enr.people ?? [];
  return (
    <li className="px-3.5 py-2.5">
      <div className="flex items-center gap-2 text-[11px] text-mute">
        <span className={`uppercase tracking-wider font-medium ${f.priority === "high" ? "text-accent" : ""}`}>
          {CATEGORY_LABEL[f.category ?? ""] ?? f.category}
        </span>
        <span>·</span>
        <time title={istTime(f.published_at)}>{ago(f.published_at)}</time>
      </div>
      <p className="text-[15px] leading-snug mt-0.5">{text}</p>

      {enr.results && (
        <div className="mt-2">
          <ResultsTable c={enr.results} lender={enr.results.rows?.[1]?.value == null} />
        </div>
      )}

      {people.length > 0 && (
        <ul className="mt-2 space-y-2">
          {people.slice(0, 3).map((p) => (
            <li key={p.name} className="text-[13px]">
              <div>
                <span className={p.direction === "joining" ? "text-up" : "text-down"}>{p.direction === "joining" ? "In" : "Out"}</span>{" "}
                <span className="font-medium">{p.name}</span>
                {p.role && <span className="text-mute"> · {p.role}</span>}
              </div>
              {p.profile ? (
                <p className="text-mute leading-snug mt-0.5">{p.profile.length > 240 ? p.profile.slice(0, 237) + "…" : p.profile}</p>
              ) : (
                p.direction === "joining" && <p className="text-mute text-[12px]">No profile in the filing.</p>
              )}
            </li>
          ))}
        </ul>
      )}

      {enr.key_sentence && !people.length && (
        <p className="mt-1.5 text-[13px] text-mute leading-snug border-l-2 border-line pl-2.5">“{enr.key_sentence}”</p>
      )}

      {f.category === "management_change" && f.network && f.network.length > 0 && (
        <div className="mt-2 rounded-lg bg-bg/60 border border-line px-2.5 py-1">
          <div className="text-[10px] uppercase tracking-wider text-accent font-semibold pt-1">
            {f.category === "management_change" ? "Your network" : "Who to call"}
          </div>
          {f.network.slice(0, 2).map((g, i) => (
            <div key={i}>
              {g.for && f.network!.length > 1 && <div className="text-[11px] text-mute pt-1">re {g.for}</div>}
              {g.results.slice(0, 2).map((s) => (
                <PersonRow key={s.person_id} s={s} compact />
              ))}
            </div>
          ))}
        </div>
      )}

      {f.attachment_url && (
        <a href={f.attachment_url} target="_blank" rel="noreferrer" className="text-xs text-mute underline underline-offset-2 mt-1.5 inline-block">
          Filing PDF ↗
        </a>
      )}
    </li>
  );
}

function Routine({ groups, total }: { groups: Feed["routine"]; total: number }) {
  const [open, setOpen] = useState(false);
  const [openCat, setOpenCat] = useState<string | null>(null);
  return (
    <section className="rounded-xl border border-line">
      <button onClick={() => setOpen(!open)} className="w-full px-3.5 py-3 flex items-center justify-between gap-3 text-sm">
        <span className="text-mute truncate text-left">
          {total} routine filing{total === 1 ? "" : "s"}
          <span className="ml-1.5 text-xs">
            ({groups.slice(0, 3).map((g) => `${g.count} ${(CATEGORY_LABEL[g.category ?? ""] ?? "other").toLowerCase()}`).join(", ")}
            {groups.length > 3 ? ", …" : ""})
          </span>
        </span>
        <span className="text-mute">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <ul className="border-t border-line divide-y divide-line">
          {groups.map((g) => {
            const key = g.category ?? "none";
            return (
              <li key={key}>
                <button onClick={() => setOpenCat(openCat === key ? null : key)} className="w-full px-3.5 py-2.5 flex justify-between text-sm">
                  <span>{CATEGORY_LABEL[g.category ?? ""] ?? "Other"}</span>
                  <span className="text-mute num">{g.count}</span>
                </button>
                {openCat === key && (
                  <ul className="pb-2">
                    {g.items.map((f) => (
                      <li key={f.id} className="px-3.5 py-1.5 text-[13px] flex gap-2">
                        <span className="font-medium w-24 shrink-0 truncate">{f.symbol}</span>
                        <span className="text-mute flex-1 min-w-0">
                          {f.attachment_url ? (
                            <a href={f.attachment_url} target="_blank" rel="noreferrer" className="hover:text-ink">
                              {f.headline}
                            </a>
                          ) : (
                            f.headline
                          )}
                        </span>
                        <span className="text-mute text-xs shrink-0">{ago(f.published_at)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
