import { useEffect, useState } from "react";
import { api, net, type AskResult } from "../api";
import { PersonRow, SyntheticNote } from "../components";
import { go } from "../nav";
import { KeepWarmList } from "./People";
import { QAView } from "./CompanyQA";


export default function Ask() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<AskResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run(text: string) {
    if (!text.trim()) return;
    setQ(text);
    setBusy(true);
    setErr(null);
    try {
      const r = await net.ask(text);
      if (r.type === "company") {
        go({ company: r.symbol });
        return;
      }
      setRes(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pb-24 px-4">
      <header className="pt-4">
        <div className="text-[11px] uppercase tracking-[0.14em] text-mute">Ask FINN</div>
        <h1 className="text-lg font-semibold">Research a company, or find who to call</h1>
      </header>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(q);
        }}
        className="mt-3 flex gap-2"
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Any NSE ticker, a person, or a theme…"
          className="flex-1 h-11 rounded-xl bg-card border border-line px-3 text-[15px] outline-none focus:border-accent"
          autoCapitalize="none"
          enterKeyHint="search"
        />
        <button disabled={busy} className="h-11 px-4 rounded-xl bg-accent text-black font-semibold disabled:opacity-50">
          {busy ? "…" : "Ask"}
        </button>
      </form>
      {err && <div className="mt-4 text-sm text-down">{err}</div>}
      {res ? (
        <>
          <Answer r={res} onExample={run} />
          <button onClick={() => setRes(null)} className="mt-6 text-sm text-mute underline">
            ← More things to ask
          </button>
        </>
      ) : (
        <StartHere run={run} />
      )}
    </div>
  );
}

const GROUPS: { title: string; hint: string; items: string[] }[] = [
  {
    title: "Research any NSE company",
    hint: "numbers, promises vs delivery, sources",
    items: ["Research DIXON", "Adani Power", "What did ASTRAL say about PVC prices?", "What is Dixon's display capex plan?"],
  },
  {
    title: "Who should I call?",
    hint: "people who worked there, at a rival, or know the theme",
    items: ["Who should I call about ASTRAL?", "Who knows specialty chemicals?", "Who knows rural lending?"],
  },
  {
    title: "People in the news",
    hint: "new appointees from filings, and your paths to them",
    items: ["Who can introduce me to Prithvi Vachani?", "Who knows V. N. Srivatsan?"],
  },
  { title: "Keep the network warm", hint: "", items: ["Who should I reconnect with?"] },
];

/** Empty state: what FINN can do, as tappable questions, plus one-tap research on holdings. */
function StartHere({ run }: { run: (q: string) => void }) {
  const [holdings, setHoldings] = useState<{ symbol: string; kind: string }[]>([]);
  useEffect(() => {
    api.watchlist().then((w) => setHoldings(w.map((x) => ({ symbol: x.company.nse_symbol ?? "", kind: x.kind }))));
  }, []);
  return (
    <div className="mt-5 space-y-5">
      {GROUPS.map((g) => (
        <section key={g.title}>
          <div className="text-[13px] font-semibold">{g.title}</div>
          {g.hint && <div className="text-[11px] text-mute">{g.hint}</div>}
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {g.items.map((q) => (
              <button
                key={q}
                onClick={() => run(q)}
                className="h-8 px-3 rounded-full border border-line text-[13px] text-mute hover:text-ink hover:border-ink/40"
              >
                {q}
              </button>
            ))}
          </div>
        </section>
      ))}
      {holdings.length > 0 && (
        <section>
          <div className="text-[13px] font-semibold">Your names</div>
          <div className="text-[11px] text-mute">tap to open research · outlined = research list</div>
          <div className="mt-1.5 grid grid-cols-4 gap-1.5">
            {holdings.map((h) => (
              <button
                key={h.symbol}
                onClick={() => go({ company: h.symbol })}
                className={`h-9 rounded-lg text-[12px] font-medium truncate px-1 ${
                  h.kind === "portfolio" ? "bg-card border border-line" : "border border-dashed border-line text-mute"
                }`}
              >
                {h.symbol}
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Answer({ r, onExample }: { r: AskResult; onExample: (q: string) => void }) {
  return (
    <section className="mt-5">
      <h2 className="font-semibold">{r.title}</h2>
      {r.type === "help" && (
        <ul className="mt-2 text-sm text-mute space-y-1">
          {r.examples.map((e) => (
            <li key={e}>
              <button className="underline" onClick={() => onExample(e)}>
                {e}
              </button>
            </li>
          ))}
        </ul>
      )}
      {r.type === "person_reach" && (
        <div className="mt-2 rounded-xl border border-line bg-card p-3 text-[13px]">
          <div className="font-medium">
            {r.person.name} · {r.person.role ?? "senior management"}
          </div>
          <div className="text-mute">
            {r.person.direction === "joining" ? "Joining" : "Leaving"} {r.person.company} ·{" "}
            <a className="underline" href={r.person.filing_url} target="_blank" rel="noreferrer">
              filing
            </a>
          </div>
          {r.person.profile && <p className="mt-1.5 leading-snug">{r.person.profile}</p>}
        </div>
      )}
      {(r.type === "who_to_call" || r.type === "expertise" || r.type === "person_reach") && (
        <>
          {r.results.length === 0 ? (
            <p className="mt-2 text-sm text-mute">No one in your network matches yet.</p>
          ) : (
            <div className="mt-1 divide-y divide-line">
              {r.results.map((s) => (
                <PersonRow key={s.person_id} s={s} />
              ))}
            </div>
          )}
          {r.type === "who_to_call" && (
            <button onClick={() => go({ company: r.symbol })} className="mt-2 text-sm underline">
              Open {r.symbol} research →
            </button>
          )}
          <SyntheticNote />
        </>
      )}
      {r.type === "company_qa" && (
        <>
          <QAView r={r.qa} />
          <button onClick={() => go({ company: r.symbol })} className="mt-3 text-sm underline">
            Open {r.symbol} research →
          </button>
        </>
      )}
      {r.type === "keep_warm" && <KeepWarmList items={r.results} />}
      {r.type === "person" && (
        <button onClick={() => go({ person: r.person.id })} className="mt-2 text-sm underline">
          Open {r.person.name} →
        </button>
      )}
    </section>
  );
}
