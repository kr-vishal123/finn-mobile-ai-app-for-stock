import { useState } from "react";
import { net, type QA } from "../api";

const SUGGEST = [
  "What did management say about margins?",
  "What are the capex plans?",
  "What is the demand outlook?",
  "What risks did analysts press on?",
];

/** Ask a question about this company — answered only from its own earnings calls, with verified quotes. */
export function CompanyAsk({ symbol }: { symbol: string }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<QA | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run(text: string) {
    if (text.trim().length < 3) return;
    setQ(text);
    setBusy(true);
    setErr(null);
    try {
      setRes(await net.companyAsk(symbol, text));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-accent/40 bg-card p-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(q);
        }}
        className="flex gap-2"
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={`Ask ${symbol}'s earnings calls…`}
          className="flex-1 min-w-0 h-10 rounded-lg bg-bg border border-line px-3 text-[14px] outline-none focus:border-accent"
          enterKeyHint="search"
        />
        <button disabled={busy} className="h-10 px-3 rounded-lg bg-accent text-black text-sm font-semibold disabled:opacity-50">
          {busy ? "…" : "Ask"}
        </button>
      </form>
      {!res && !busy && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {SUGGEST.map((s) => (
            <button key={s} onClick={() => run(s)} className="h-7 px-2.5 rounded-full border border-line text-[12px] text-mute">
              {s}
            </button>
          ))}
        </div>
      )}
      {busy && <div className="mt-2 text-[13px] text-mute">Reading the last four calls…</div>}
      {err && <div className="mt-2 text-[13px] text-down">{err}</div>}
      {res && !busy && <QAView r={res} />}
    </div>
  );
}

export function QAView({ r }: { r: QA }) {
  return (
    <div className="mt-2">
      {r.mode === "answer" && r.answer && (
        <>
          <p className={`text-[14px] leading-relaxed ${r.not_found ? "text-mute" : ""}`}>{r.answer}</p>
          {r.citations.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {r.citations.map((c, i) => (
                <li key={i} className="text-[12px] leading-snug border-l-2 border-accent/50 pl-2">
                  <span className="text-ink/90">“{c.quote}”</span>{" "}
                  <a href={c.url} target="_blank" rel="noreferrer" className="text-mute underline whitespace-nowrap">
                    {c.ref}
                  </a>
                </li>
              ))}
            </ul>
          )}
          <div className="text-[10px] text-mute mt-2">
            Answered by {r.model} from the company's own transcripts only · every quote checked word-for-word against the
            cited page{r.unverified_dropped ? ` · ${r.unverified_dropped} unverifiable quote(s) removed` : ""}
          </div>
        </>
      )}
      {r.mode !== "answer" && (
        <>
          {r.note && <div className="text-[12px] text-mute">{r.note}</div>}
          <ul className="mt-1.5 space-y-2">
            {r.passages.slice(0, 4).map((p, i) => (
              <li key={i} className="text-[12px] leading-snug border-l-2 border-line pl-2">
                “{p.snippet}”{" "}
                <a href={p.url} target="_blank" rel="noreferrer" className="text-mute underline whitespace-nowrap">
                  {p.ref}
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
