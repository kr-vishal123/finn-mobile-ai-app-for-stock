"""Fundamentals from screener.in: standardised quarterly/annual financials + links to the
primary documents (concall transcripts, investor decks, annual reports).

Lazy and per ticker, so any NSE symbol works: the first request fetches, later ones hit the DB.
Parsed output is snapshotted as small JSON (snapshots/screener/) as a fallback.

Numbers here are the "actuals" side of Pull and the results card. Screener restates each
company's exchange-filed results in a standard layout; we keep its row names in `extra`.
"""

import calendar
import json
import logging
import re
from datetime import date, datetime, timedelta

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.db import utcnow
from app.models import Company, Document, FinancialPeriod
from app.models.enums import DocType, PeriodType

log = logging.getLogger(__name__)
SNAP_DIR = BACKEND_DIR / "snapshots" / "screener"
_MONTHS = {m: i for i, m in enumerate(calendar.month_abbr) if m}


# ---------------------------------------------------------------- parsing helpers


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    t = s.replace(",", "").replace("%", "").replace("₹", "").replace("Cr.", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _key(label: str) -> str:
    label = label.replace("+", "").replace("%", " pct").strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", label).strip("_")


def _month_end(label: str) -> date | None:
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", label.strip())
    if not m or m.group(1) not in _MONTHS:
        return None
    y, mo = int(m.group(2)), _MONTHS[m.group(1)]
    return date(y, mo, calendar.monthrange(y, mo)[1])


def fy_label(d: date, quarter: bool) -> str:
    """Indian fiscal year ends in March. Sep 2026 → Q2FY27; Mar 2026 → FY26."""
    fy = d.year + 1 if d.month >= 4 else d.year
    if not quarter:
        return f"FY{fy % 100:02d}"
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(d.month, (d.month - 4) % 12 // 3 + 1)
    return f"Q{q}FY{fy % 100:02d}"


def discussed_quarter(call_month: date) -> date:
    """An earnings call in month M discusses the last quarter that ended before M."""
    y, m = call_month.year, call_month.month
    for qm in (12, 9, 6, 3):
        if qm < m:
            return date(y, qm, calendar.monthrange(y, qm)[1])
    return date(y - 1, 12, 31)


def _table(soup: BeautifulSoup, section_id: str) -> tuple[list[str], dict[str, list[float | None]]]:
    sec = soup.find("section", id=section_id)
    t = sec.find("table") if sec else None
    if t is None:
        return [], {}
    heads = [th.get_text(strip=True) for th in t.find("thead").find_all("th")][1:]
    rows: dict[str, list[float | None]] = {}
    for tr in t.find("tbody").find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        label = tds[0].get_text(" ", strip=True)
        # strip screener's hover help text ("CFO/EBITDA Share of operating ...")
        label = label.split(" Share of")[0]
        k = _key(label)
        if k in ("raw_pdf",) or not k:
            continue
        rows[k] = [_num(td.get_text(strip=True)) for td in tds[1:]]
    return heads, rows


def parse_screener(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {"quarters": [], "annual": [], "documents": [], "about": None, "ratios": {}}

    about = soup.select_one(".company-profile .about")
    out["about"] = about.get_text(" ", strip=True) if about else None
    for li in soup.select("#top-ratios li"):
        name = li.select_one(".name")
        val = li.select_one(".number")
        if name and val:
            out["ratios"][_key(name.get_text(strip=True))] = _num(val.get_text(strip=True))

    heads, rows = _table(soup, "quarters")
    for i, h in enumerate(heads):
        d = _month_end(h)
        if d:
            out["quarters"].append({"period_end": d.isoformat(), "row": {k: v[i] for k, v in rows.items() if i < len(v)}})

    heads, pl = _table(soup, "profit-loss")
    extra_tables = {}
    for sec in ("balance-sheet", "cash-flow", "ratios"):
        h2, r2 = _table(soup, sec)
        extra_tables[sec] = {hh: {k: v[j] for k, v in r2.items() if j < len(v)} for j, hh in enumerate(h2)}
    for i, h in enumerate(heads):
        d = _month_end(h)
        if not d:  # skips TTM
            continue
        row = {k: v[i] for k, v in pl.items() if i < len(v)}
        for sec, cols in extra_tables.items():
            for k, v in cols.get(h, {}).items():
                row[f"{sec.replace('-', '_')}.{k}"] = v
        out["annual"].append({"period_end": d.isoformat(), "row": row})

    docs = soup.find("section", id="documents")
    if docs:
        for li in docs.select(".concalls li"):
            parts = li.get_text(" | ", strip=True).split(" | ")
            when = _month_end(parts[0]) if parts else None
            for a in li.find_all("a"):
                kind = a.get_text(strip=True).lower()
                href = a.get("href") or ""
                if not href.startswith("http"):
                    continue
                if kind == "transcript":
                    out["documents"].append({"doc_type": "concall_transcript", "url": href,
                                             "date": when.isoformat() if when else None})
                elif kind == "ppt":
                    out["documents"].append({"doc_type": "investor_presentation", "url": href,
                                             "date": when.isoformat() if when else None})
        for li in docs.select(".annual-reports li"):
            a = li.find("a")
            m = re.search(r"(\d{4})", li.get_text(" ", strip=True))
            if a and (a.get("href") or "").startswith("http"):
                out["documents"].append({"doc_type": "annual_report", "url": a["href"],
                                         "date": f"{m.group(1)}-03-31" if m else None})
    return out


# ---------------------------------------------------------------- fetch + store


def fetch_screener(symbol: str) -> dict:
    s = get_settings()
    headers = {"User-Agent": s.http_user_agent}
    last: dict = {}
    for variant in ("consolidated/", ""):  # some companies only report standalone
        r = httpx.get(f"{s.screener_base_url}/company/{symbol}/{variant}", headers=headers,
                      timeout=30, follow_redirects=True)
        if r.status_code == 404:
            break
        r.raise_for_status()
        last = parse_screener(r.text) | {"consolidated": variant == "consolidated/"}
        if last["quarters"] and any(q["row"].get("sales") or q["row"].get("revenue") for q in last["quarters"]):
            return last
    if not last:
        raise LookupError(f"{symbol} not found on screener")
    return last


def _first(row: dict, *keys: str) -> float | None:
    for k in keys:
        if row.get(k) is not None:
            return row[k]
    return None


def store(db: Session, company: Company, data: dict) -> None:
    consolidated = bool(data.get("consolidated", True))
    db.execute(delete(FinancialPeriod).where(FinancialPeriod.company_id == company.id,
                                             FinancialPeriod.source == "screener"))
    for ptype, items in ((PeriodType.quarter, data["quarters"]), (PeriodType.annual, data["annual"])):
        for it in items:
            d = date.fromisoformat(it["period_end"])
            row = it["row"]
            db.add(FinancialPeriod(
                company_id=company.id, period_type=ptype, period_end=d,
                label=fy_label(d, ptype == PeriodType.quarter), consolidated=consolidated,
                revenue=_first(row, "sales", "revenue"),
                # EBITDA isn't meaningful for lenders (screener's "financing profit" excludes
                # other income and goes negative), so banks/NBFCs get None, not a wrong number.
                ebitda=row.get("operating_profit"),
                pbt=row.get("profit_before_tax"), pat=row.get("net_profit"),
                eps=row.get("eps_in_rs"), extra=row, source="screener",
            ))
    existing = {d.url: d for d in db.scalars(select(Document).where(Document.company_id == company.id))}
    seen = set(existing)
    for doc in data["documents"]:
        if doc["url"] in seen:
            old = existing.get(doc["url"])
            if old is not None and old.doc_date and old.doc_type == DocType.concall_transcript:
                old.period_label = fy_label(discussed_quarter(old.doc_date), True)
            continue
        seen.add(doc["url"])
        d = date.fromisoformat(doc["date"]) if doc.get("date") else None
        is_ar = doc["doc_type"] == "annual_report"
        db.add(Document(
            company_id=company.id, doc_type=DocType(doc["doc_type"]), url=doc["url"], doc_date=d,
            period_label=(fy_label(d, False) if is_ar else fy_label(discussed_quarter(d), True)) if d else None,
            title={"concall_transcript": "Earnings call transcript", "investor_presentation": "Investor presentation",
                   "annual_report": "Annual report"}[doc["doc_type"]],
        ))
    latest_fy = max((FinancialPeriod_ for FinancialPeriod_ in db.new if isinstance(FinancialPeriod_, FinancialPeriod)
                     and FinancialPeriod_.period_type == PeriodType.annual), key=lambda p: p.period_end, default=None)
    if latest_fy is not None and data.get("ratios"):
        latest_fy.extra = {**(latest_fy.extra or {}), "top_ratios": data["ratios"]}
    if data.get("about"):
        company.description = data["about"]
    if data.get("ratios", {}).get("market_cap"):
        company.market_cap_cr = data["ratios"]["market_cap"]
    db.flush()


def ensure_fundamentals(db: Session, company: Company, max_age_hours: int = 24, live: bool = True) -> str:
    """Return 'cached' | 'live' | 'snapshot' | 'unavailable'."""
    newest = db.scalar(select(FinancialPeriod.created_at).where(
        FinancialPeriod.company_id == company.id).order_by(FinancialPeriod.created_at.desc()).limit(1))
    if newest is not None:
        newest = newest if newest.tzinfo else newest.replace(tzinfo=utcnow().tzinfo)
        if utcnow() - newest < timedelta(hours=max_age_hours) or not live:
            return "cached"
    snap = SNAP_DIR / f"{company.nse_symbol}.json"
    data, how = None, "unavailable"
    if live:
        try:
            data, how = fetch_screener(company.nse_symbol), "live"
            SNAP_DIR.mkdir(parents=True, exist_ok=True)
            snap.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except (httpx.HTTPError, LookupError, AttributeError) as e:
            log.warning("screener fetch failed for %s: %s", company.nse_symbol, e)
    if data is None and snap.exists():
        data, how = json.loads(snap.read_text(encoding="utf-8")), "snapshot"
    if data is None:
        return newest and "cached" or "unavailable"
    store(db, company, data)
    db.commit()
    return how


# ---------------------------------------------------------------- derived views (pure code)


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1) * 100 * (1 if b > 0 else -1)


def headline_compare(quarters: list[FinancialPeriod], idx: int = 0) -> dict | None:
    """Revenue/EBITDA/PBT/PAT for quarters[idx] vs previous quarter and same quarter last year.
    `quarters` must be sorted newest first."""
    if len(quarters) <= idx:
        return None
    cur = quarters[idx]
    prev = quarters[idx + 1] if len(quarters) > idx + 1 else None
    yago = next((q for q in quarters if q.period_end.year == cur.period_end.year - 1
                 and q.period_end.month == cur.period_end.month), None)
    rows = []
    for m, label in (("revenue", "Revenue"), ("ebitda", "EBITDA"), ("pbt", "PBT"), ("pat", "PAT")):
        v = getattr(cur, m)
        rows.append({
            "metric": label, "value": v,
            "prev": getattr(prev, m) if prev else None, "yago": getattr(yago, m) if yago else None,
            "qoq": pct(v, getattr(prev, m)) if prev else None,
            "yoy": pct(v, getattr(yago, m)) if yago else None,
        })
    checks = []
    if cur.revenue and cur.ebitda and cur.ebitda > cur.revenue:
        checks.append("EBITDA exceeds revenue")
    if cur.pbt is not None and cur.pat is not None and cur.pat > cur.pbt and cur.pbt > 0:
        checks.append("PAT exceeds PBT (tax credit or minority interest)")
    margin = (cur.ebitda / cur.revenue * 100) if cur.revenue and cur.ebitda else None
    prev_margin = (prev.ebitda / prev.revenue * 100) if prev and prev.revenue and prev.ebitda else None
    yago_margin = (yago.ebitda / yago.revenue * 100) if yago and yago.revenue and yago.ebitda else None
    return {
        "label": cur.label, "period_end": cur.period_end.isoformat(),
        "prev_label": prev.label if prev else None, "yago_label": yago.label if yago else None,
        "rows": rows, "ebitda_margin": margin, "ebitda_margin_prev": prev_margin,
        "ebitda_margin_yago": yago_margin, "checks": checks,
        "consolidated": cur.consolidated, "source": "screener.in (restated from exchange filing)",
    }
