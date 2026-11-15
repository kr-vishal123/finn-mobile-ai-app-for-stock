import { useEffect, useState } from "react";
import { CATEGORY_LABEL, net, type KeepWarm, type PersonCard, type Suggestion } from "../api";
import { Avatar, lastSpoke, PersonRow, relLabel, Section, Strength, SyntheticNote } from "../components";
import { go } from "../nav";

/** People: what the network can do for you today — not a contact list. */
export default function People() {
  const [warm, setWarm] = useState<KeepWarm[] | null>(null);
  const [themes, setThemes] = useState<{ theme: string; people: number }[]>([]);
  const [theme, setTheme] = useState<string | null>(null);
  const [experts, setExperts] = useState<Suggestion[] | null>(null);

  useEffect(() => {
    net.keepWarm().then(setWarm);
    net.themes().then(setThemes);
  }, []);
  useEffect(() => {
    if (theme) net.expertise(theme).then(setExperts);
  }, [theme]);

  return (
    <div className="pb-24 px-4">
      <header className="pt-4">
        <div className="text-[11px] uppercase tracking-[0.14em] text-mute">Your network</div>
        <h1 className="text-lg font-semibold">
          {warm ? `${warm.length} people worth a call this week` : "Loading…"}
        </h1>
      </header>

      <Section title="Reconnect" hint="news at their (ex-)employer, quiet for 4+ months">
        {warm && <KeepWarmList items={warm.slice(0, 6)} />}
      </Section>

      <Section title="Expertise map" hint="tap a theme">
        <div className="flex flex-wrap gap-1.5">
          {themes.slice(0, 28).map((t) => (
            <button
              key={t.theme}
              onClick={() => setTheme(t.theme === theme ? null : t.theme)}
              className={`h-8 px-3 rounded-full text-[13px] border ${
                t.theme === theme ? "bg-ink text-bg border-ink" : "border-line text-mute"
              }`}
            >
              {t.theme}
              {t.people > 1 && <span className="ml-1 num opacity-70">{t.people}</span>}
            </button>
          ))}
        </div>
        {theme && experts && (
          <div className="mt-2 divide-y divide-line">
            {experts.map((s) => (
              <PersonRow key={s.person_id} s={s} compact />
            ))}
          </div>
        )}
      </Section>
      <SyntheticNote />
    </div>
  );
}

export function KeepWarmList({ items }: { items: KeepWarm[] }) {
  if (items.length === 0) return <p className="text-sm text-mute">Everyone's warm.</p>;
  return (
    <ul className="divide-y divide-line">
      {items.map((k) => (
        <li key={k.person_id} className="py-2.5 flex gap-2.5">
          <Avatar name={k.name} />
          <div className="min-w-0 flex-1">
            <button onClick={() => go({ person: k.person_id })} className="font-medium text-[14px]">
              {k.name}
            </button>
            <span className="text-[11px] text-mute ml-2">{lastSpoke(k.last_spoke_days)}</span>
            <div className="text-[13px] leading-snug mt-0.5">
              <button onClick={() => go({ company: k.symbol })} className="text-accent font-medium mr-1">
                {k.symbol}
              </button>
              <span className="text-mute">{CATEGORY_LABEL[k.category ?? ""] ?? ""}:</span> {k.hook.split(": ").slice(1).join(": ")}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function PersonView({ id }: { id: number }) {
  const [p, setP] = useState<PersonCard | null>(null);
  useEffect(() => {
    net.person(id).then(setP);
  }, [id]);
  return (
    <div className="pb-24">
      <header className="sticky top-0 z-10 bg-bg/90 backdrop-blur border-b border-line px-4 py-3 flex items-center gap-3">
        <button onClick={() => history.back()} className="text-mute text-lg leading-none" aria-label="Back">
          ←
        </button>
        <div className="font-semibold">{p?.name ?? "…"}</div>
      </header>
      {p && (
        <main className="px-4 pt-3">
          <div className="flex gap-3 items-center">
            <Avatar name={p.name} dim={!p.relationship} />
            <div>
              <div className="text-[13px]">{p.headline}</div>
              <div className="text-xs text-mute">
                {relLabel(p.relationship)} <Strength n={p.strength} /> {lastSpoke(p.last_spoke_days) && `· ${lastSpoke(p.last_spoke_days)}`}
              </div>
            </div>
          </div>
          {p.how_met && <p className="text-[13px] text-mute mt-2">{p.how_met}</p>}
          {p.path && (
            <p className="text-[13px] mt-2">
              Not a direct contact. Intro via <b>{p.path[0].name}</b> — {p.path[0].evidence}.
            </p>
          )}
          <Section title="Career">
            <ul className="space-y-1.5 text-[13px]">
              {p.experiences.map((e, i) => (
                <li key={i} className="flex justify-between gap-3">
                  <span>
                    {e.title},{" "}
                    {e.symbol ? (
                      <button className="underline" onClick={() => go({ company: e.symbol! })}>
                        {e.org}
                      </button>
                    ) : (
                      e.org
                    )}
                  </span>
                  <span className="text-mute num shrink-0">{e.years}</span>
                </li>
              ))}
            </ul>
          </Section>
          <Section title="Education">
            <ul className="space-y-1 text-[13px]">
              {p.educations.map((e, i) => (
                <li key={i} className="flex justify-between gap-3">
                  <span>
                    {e.degree}, {e.institution}
                  </span>
                  <span className="text-mute num">{e.years}</span>
                </li>
              ))}
            </ul>
          </Section>
          <Section title="Go-to for">
            <div className="flex flex-wrap gap-1.5">
              {p.expertise.map((t) => (
                <span key={t} className="h-7 px-2.5 rounded-full border border-line text-[12px] inline-flex items-center">
                  {t}
                </span>
              ))}
            </div>
          </Section>
          <p className="text-[11px] text-mute mt-4">Profile source: {p.source} (fictional person for the demo).</p>
        </main>
      )}
    </div>
  );
}
