import type { ResultsCompare } from "../api";
import { Delta } from "../components";

/** Revenue / EBITDA / PBT / PAT this quarter, QoQ and YoY. Numbers computed server-side in code. */
export function ResultsTable({ c, lender = false }: { c: ResultsCompare; lender?: boolean }) {
  return (
    <div>
      <table className="w-full text-[13px] num">
        <thead>
          <tr className="text-mute text-[11px]">
            <th className="text-left font-normal py-1">₹ cr</th>
            <th className="text-right font-normal">{c.label}</th>
            <th className="text-right font-normal">QoQ</th>
            <th className="text-right font-normal">YoY</th>
          </tr>
        </thead>
        <tbody>
          {c.rows.map((r) =>
            r.metric === "EBITDA" && (lender || r.value === null) ? (
              <tr key={r.metric} className="border-t border-line">
                <td className="py-1.5">EBITDA</td>
                <td colSpan={3} className="text-right text-mute text-[11px]">
                  not meaningful for lenders
                </td>
              </tr>
            ) : (
              <tr key={r.metric} className="border-t border-line">
                <td className="py-1.5">{r.metric}</td>
                <td className="text-right font-medium">{r.value?.toLocaleString("en-IN", { maximumFractionDigits: 0 }) ?? "—"}</td>
                <td className="text-right">
                  <Delta v={r.qoq} />
                </td>
                <td className="text-right">
                  <Delta v={r.yoy} />
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
      {!lender && c.ebitda_margin != null && (
        <div className="text-[12px] text-mute mt-1.5">
          EBITDA margin <span className="text-ink num">{c.ebitda_margin.toFixed(1)}%</span>
          {c.ebitda_margin_yago != null && (
            <>
              {" "}
              vs {c.ebitda_margin_yago.toFixed(1)}% a year ago (
              <Delta v={c.ebitda_margin - c.ebitda_margin_yago} suffix=" pts" />)
            </>
          )}
        </div>
      )}
      {c.checks.length > 0 && <div className="text-[11px] text-accent mt-1">Check: {c.checks.join("; ")}</div>}
    </div>
  );
}
