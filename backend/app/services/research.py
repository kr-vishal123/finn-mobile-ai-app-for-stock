"""Pull: a research view of any NSE company, grounded only in primary data.

Sections (numbers are code, never a model):
  snapshot     — what it does (company's own description), size, headline ratios
  financials   — latest quarter vs QoQ/YoY, trailing four quarters
  trajectory   — multi-year revenue / margin / profit with CAGRs and what's compressing
  balance      — leverage and working-capital cycle
  cash         — cash conversion: CFO vs EBITDA and vs PAT, free cash flow
  narrative    — management's promises (verbatim, with page) vs delivered
  signals      — the facts above, sorted into what supports a bull or a bear case
  sources      — every document used, linked
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Document, FinancialPeriod, GuidanceItem, User
from app.models.enums import DocType, PeriodType
from app.services.fundamentals import headline_compare, pct
from app.services.network import who_to_call


def _cagr(a: float | None, b: float | None, years: int) -> float | None:
    if not a or not b or a <= 0 or b <= 0 or years <= 0:
        return None
    return ((a / b) ** (1 / years) - 1) * 100


def _r(x: float | None, n: int = 1) -> float | None:
    return None if x is None else round(x, n)


def build_research(db: Session, user: User, company: Company) -> dict:
    q = list(db.scalars(select(FinancialPeriod).where(
        FinancialPeriod.company_id == company.id, FinancialPeriod.period_type == PeriodType.quarter)
        .order_by(FinancialPeriod.period_end.desc())))
    a = list(db.scalars(select(FinancialPeriod).where(
        FinancialPeriod.company_id == company.id, FinancialPeriod.period_type == PeriodType.annual)
        .order_by(FinancialPeriod.period_end)))
    is_lender = bool(q and q[0].ebitda is None and (q[0].extra or {}).get("financing_profit") is not None)
    latest_fy = a[-1] if a else None
    ratios = (latest_fy.extra or {}).get("top_ratios", {}) if latest_fy else {}

    # ---- trailing four quarters
    ttm = None
    if len(q) >= 8:
        cur4, prev4 = q[:4], q[4:8]
        s = lambda rows, m: sum(getattr(r, m) or 0 for r in rows)  # noqa: E731
        ttm = {
            "revenue": s(cur4, "revenue"), "pat": s(cur4, "pat"),
            "revenue_growth": _r(pct(s(cur4, "revenue"), s(prev4, "revenue"))),
            "pat_growth": _r(pct(s(cur4, "pat"), s(prev4, "pat"))),
            "ebitda_margin": _r(s(cur4, "ebitda") / s(cur4, "revenue") * 100) if not is_lender and s(cur4, "revenue") else None,
        }

    # ---- multi-year trajectory
    years = []
    for p in a:
        ex = p.extra or {}
        years.append({
            "label": p.label, "revenue": p.revenue, "ebitda": p.ebitda, "pat": p.pat,
            "ebitda_margin": _r(p.ebitda / p.revenue * 100) if p.ebitda and p.revenue else None,
            "cfo": ex.get("cash_flow.cash_from_operating_activity"),
            "fcf": ex.get("cash_flow.free_cash_flow"),
            "borrowings": ex.get("balance_sheet.borrowings", ex.get("balance_sheet.borrowing")),
            "equity": (ex.get("balance_sheet.equity_capital") or 0) + (ex.get("balance_sheet.reserves") or 0) or None,
            "ccc": ex.get("ratios.cash_conversion_cycle"), "debtor_days": ex.get("ratios.debtor_days"),
            "inventory_days": ex.get("ratios.inventory_days"), "roce": ex.get("ratios.roce_pct"),
        })
    traj: dict = {"years": years[-6:]}
    if len(a) >= 4:
        last, base3 = a[-1], a[-4]
        traj["revenue_cagr_3y"] = _r(_cagr(last.revenue, base3.revenue, 3))
        traj["pat_cagr_3y"] = _r(_cagr(last.pat, base3.pat, 3))
        m_now, m_then = years[-1]["ebitda_margin"], years[-4]["ebitda_margin"]
        traj["margin_change_3y_pts"] = _r(m_now - m_then) if m_now is not None and m_then is not None else None

    # ---- balance sheet & cash quality (last reported year, and 5-year cumulative)
    bal = cash = None
    if years:
        y = years[-1]
        de = y["borrowings"] / y["equity"] if y["borrowings"] is not None and y["equity"] else None
        prev_ccc = years[-4]["ccc"] if len(years) >= 4 else None
        bal = {"borrowings": y["borrowings"], "equity": y["equity"], "debt_to_equity": _r(de, 2),
               "ccc_days": y["ccc"], "ccc_days_3y_ago": prev_ccc, "debtor_days": y["debtor_days"],
               "inventory_days": y["inventory_days"], "label": y["label"]}
        last5 = [x for x in years[-5:] if x["cfo"] is not None]
        cfo5 = sum(x["cfo"] for x in last5)
        pat5 = sum(x["pat"] or 0 for x in last5)
        eb5 = sum(x["ebitda"] or 0 for x in last5)
        cash = {"cfo_5y": cfo5, "pat_5y": pat5, "fcf_5y": sum(x["fcf"] or 0 for x in last5),
                "cfo_to_pat": _r(cfo5 / pat5 * 100, 0) if pat5 else None,
                "cfo_to_ebitda": _r(cfo5 / eb5 * 100, 0) if eb5 else None, "years": len(last5)}

    # ---- narrative vs numbers
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.company_id == company.id))}
    promises = []
    for g in db.scalars(select(GuidanceItem).where(GuidanceItem.company_id == company.id)
                        .order_by(GuidanceItem.said_in_period.desc())):
        d = docs.get(g.document_id)
        promises.append({
            "said_in": g.said_in_period, "metric": g.metric, "guided": g.guided_value,
            "target": g.target_period, "quote": g.quote, "page": g.page,
            "actual": _r(g.actual_value), "status": g.status.value, "assessment": g.assessment,
            "detail": (g.evidence or {}).get("detail"), "span": (g.evidence or {}).get("span"),
            "source_url": d.url if d else None,
        })

    # ---- signals: facts that support a bull vs bear case (rules over the numbers above)
    bull, bear = [], []
    rc, pc, mc = traj.get("revenue_cagr_3y"), traj.get("pat_cagr_3y"), traj.get("margin_change_3y_pts")
    if rc is not None and rc >= 12:
        bull.append(f"Revenue 3-yr CAGR {rc:.0f}%")
    elif rc is not None and rc < 6:
        bear.append(f"Revenue 3-yr CAGR only {rc:.0f}%")
    if pc is not None and rc is not None:
        if pc > rc + 3:
            bull.append(f"Profit compounding faster than revenue ({pc:.0f}% vs {rc:.0f}% CAGR)")
        elif pc < rc - 3:
            bear.append(f"Profit lagging revenue ({pc:.0f}% vs {rc:.0f}% CAGR)")
    if mc is not None and abs(mc) >= 1.5:
        (bull if mc > 0 else bear).append(f"EBITDA margin {'+' if mc > 0 else ''}{mc:.1f} pts over 3 years")
    cmp = headline_compare(q) if q else None
    if cmp:
        yoy_pat = cmp["rows"][3]["yoy"]
        yoy_rev = cmp["rows"][0]["yoy"]
        if yoy_rev is not None and yoy_pat is not None and yoy_rev > 10 and yoy_pat < 0:
            bear.append(f"{cmp['label']}: revenue +{yoy_rev:.0f}% YoY but PAT {yoy_pat:.0f}% — growth isn't reaching profit")
        elif yoy_pat is not None and yoy_pat > 20:
            bull.append(f"{cmp['label']}: PAT +{yoy_pat:.0f}% YoY")
        if cmp["ebitda_margin"] and cmp["ebitda_margin_yago"] and cmp["ebitda_margin"] < cmp["ebitda_margin_yago"] - 1.5:
            bear.append(f"{cmp['label']} EBITDA margin {cmp['ebitda_margin']:.1f}% vs {cmp['ebitda_margin_yago']:.1f}% a year ago")
    if cash and cash["cfo_to_ebitda"] is not None and not is_lender:
        if cash["cfo_to_ebitda"] >= 80:
            bull.append(f"Converts profit to cash: CFO is {cash['cfo_to_ebitda']:.0f}% of EBITDA over {cash['years']} yrs")
        elif cash["cfo_to_ebitda"] < 60:
            bear.append(f"Weak cash conversion: CFO only {cash['cfo_to_ebitda']:.0f}% of EBITDA over {cash['years']} yrs")
    if bal and bal["debt_to_equity"] is not None and not is_lender:
        if bal["debt_to_equity"] > 1:
            bear.append(f"Leverage: debt/equity {bal['debt_to_equity']:.2f}")
        elif bal["debt_to_equity"] < 0.2:
            bull.append(f"Balance sheet nearly debt-free (D/E {bal['debt_to_equity']:.2f})")
    if bal and bal["ccc_days"] is not None and bal["ccc_days_3y_ago"] is not None:
        d = bal["ccc_days"] - bal["ccc_days_3y_ago"]
        if d >= 15:
            bear.append(f"Working-capital cycle stretched {d:.0f} days in 3 yrs (now {bal['ccc_days']:.0f})")
        elif d <= -15:
            bull.append(f"Working-capital cycle tightened {abs(d):.0f} days in 3 yrs")
    missed = [p for p in promises if p["status"] == "missed"]
    kept = [p for p in promises if p["status"] in ("met", "partial")]
    if missed:
        bear.append(f"Behind on {len(missed)} explicit guidance item{'s' if len(missed) > 1 else ''}")
    if kept and not missed:
        bull.append(f"Tracking or beating {len(kept)} guidance item{'s' if len(kept) > 1 else ''}")

    sources = [{"type": d.doc_type.value, "title": d.title, "period": d.period_label, "url": d.url,
                "date": d.doc_date.isoformat() if d.doc_date else None, "used": d.status == "parsed"}
               for d in sorted(docs.values(), key=lambda d: (d.doc_date is None, d.doc_date), reverse=True)
               if d.doc_type in (DocType.concall_transcript, DocType.annual_report)][:10]

    return {
        "symbol": company.nse_symbol, "name": company.name, "sector": company.sector, "industry": company.industry,
        "market_cap_cr": company.market_cap_cr, "description": company.description, "is_lender": is_lender,
        "ratios": {k: ratios.get(k) for k in ("stock_p_e", "roce", "roe", "dividend_yield", "book_value", "current_price")},
        "latest": cmp, "ttm": ttm, "trajectory": traj, "balance": bal, "cash": cash,
        "narrative": promises, "signals": {"bull": [b for b in bull if b], "bear": bear},
        "who_to_call": who_to_call(db, user, company, limit=3), "sources": sources,
        "grounding": "Numbers: exchange-filed results as standardised by screener.in. Narrative: company "
                     "earnings-call transcripts. No news, broker notes or model knowledge.",
    }
