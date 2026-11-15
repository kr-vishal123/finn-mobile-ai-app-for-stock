import { useEffect, useState } from "react";
import { api, CATEGORY_LABEL, type AlertRule } from "../api";

const MATERIAL_CHOICES = [
  "results", "m_and_a", "management_change", "litigation", "fund_raise",
  "capex", "credit_rating", "pledging", "insider_trading", "dividend", "bonus_split",
];

/** Bottom sheet: the investor decides what "unusual" means. Saving re-evaluates alerts server-side. */
export default function AlertSettings({ onClose }: { onClose: (changed: boolean) => void }) {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [vol, setVol] = useState(2);
  const [move, setMove] = useState(5);
  const [cats, setCats] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.rules().then((rs) => {
      setRules(rs);
      for (const r of rs) {
        if (r.rule_type === "volume_spike") setVol(r.params.multiple);
        if (r.rule_type === "price_move") setMove(r.params.pct);
        if (r.rule_type === "announcement_category") setCats(r.params.categories);
      }
    });
  }, []);

  const byType = (t: AlertRule["rule_type"]) => rules.find((r) => r.rule_type === t);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const v = byType("volume_spike"), p = byType("price_move"), c = byType("announcement_category");
      if (v) await api.saveRule(v.id, { multiple: vol });
      if (p) await api.saveRule(p.id, { pct: move });
      if (c) await api.saveRule(c.id, { categories: cats });
      onClose(true);
    } catch (e: any) {
      setErr(e.message);
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center" role="dialog" aria-modal="true">
      <button className="absolute inset-0 bg-black/50" aria-label="Close" onClick={() => onClose(false)} />
      <div className="relative w-full max-w-md bg-card rounded-t-2xl border-t border-line px-4 pt-3 safe-b">
        <div className="mx-auto w-10 h-1 rounded-full bg-line mb-3" />
        <h2 className="font-semibold">What counts as unusual?</h2>
        <p className="text-sm text-mute mt-0.5">FINN watches your portfolio after every close and alerts you only past these lines.</p>

        <Slider
          label="Volume spike"
          hint="× the 20-day average"
          value={vol} min={1.5} max={6} step={0.5} fmt={(x) => `${x.toFixed(1)}×`}
          onChange={setVol}
        />
        <Slider
          label="Price move"
          hint="in a single session, either direction"
          value={move} min={2} max={12} step={0.5} fmt={(x) => `±${x.toFixed(1)}%`}
          onChange={setMove}
        />

        <div className="mt-5">
          <div className="text-sm font-medium">Filings that should alert me</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {MATERIAL_CHOICES.map((c) => {
              const on = cats.includes(c);
              return (
                <button
                  key={c}
                  onClick={() => setCats(on ? cats.filter((x) => x !== c) : [...cats, c])}
                  className={`h-8 px-3 rounded-full text-sm border ${on ? "bg-ink text-bg border-ink" : "border-line text-mute"}`}
                >
                  {CATEGORY_LABEL[c]}
                </button>
              );
            })}
          </div>
        </div>

        {err && <div className="mt-3 text-sm text-down">{err}</div>}
        <button
          onClick={save}
          disabled={saving || rules.length === 0}
          className="mt-5 mb-2 w-full h-11 rounded-xl bg-accent text-black font-semibold disabled:opacity-50"
        >
          {saving ? "Re-checking portfolio…" : "Save & re-check"}
        </button>
      </div>
    </div>
  );
}

function Slider(props: {
  label: string; hint: string; value: number; min: number; max: number; step: number;
  fmt: (x: number) => string; onChange: (x: number) => void;
}) {
  return (
    <label className="block mt-5">
      <div className="flex justify-between items-baseline">
        <span className="text-sm font-medium">{props.label}</span>
        <span className="num font-semibold text-accent">{props.fmt(props.value)}</span>
      </div>
      <input
        type="range" min={props.min} max={props.max} step={props.step} value={props.value}
        onChange={(e) => props.onChange(Number(e.target.value))}
        className="w-full mt-2 accent-[rgb(var(--accent))]"
      />
      <div className="text-xs text-mute">{props.hint}</div>
    </label>
  );
}
