"""Narrative vs numbers: what management promised on its last four calls vs what was delivered.

Promised  = explicit, numeric, forward-looking statements found in the transcripts (verbatim
            quote + page). Rules find them; a cheap model can refine when a key is configured.
Delivered = computed in code from the reported quarterly numbers. The model never does the maths.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx
from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.models import Company, Document, FinancialPeriod, GuidanceItem
from app.models.enums import DocType, GuidanceStatus, PeriodType

log = logging.getLogger(__name__)
CACHE = BACKEND_DIR / "data" / "transcripts"

# ---------------------------------------------------------------- transcript text with pages


def transcript_pages(url: str, max_pages: int = 45) -> list[str] | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    try:
        r = httpx.get(url, headers={"User-Agent": get_settings().http_user_agent}, timeout=90, follow_redirects=True)
        r.raise_for_status()
        pages = [re.sub(r"[ \t]+", " ", p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages[:max_pages]]
    except Exception as e:
        log.warning("transcript fetch failed %s: %s", url, e)
        return None
    f.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return pages


# ---------------------------------------------------------------- rules: find promises

_CUE = re.compile(
    r"\b(guidance|guide|guiding|expect|expecting|target|targeting|aim|aiming|should (?:be|grow|deliver|see)|"
    r"will (?:be|grow|deliver|see|reach|achieve)|we are confident|confident of|looking at|outlook|going forward|"
    r"sustain|maintain)\b", re.I)
_METRIC = {
    "revenue_growth": re.compile(r"\b(revenue|sales|top[- ]?line|volume|growth|grow)\b", re.I),
    "ebitda_margin": re.compile(r"\b(ebitda|operating)\s+margin|\bmargins?\b", re.I),
    "capex": re.compile(r"\bcapex\b|capital expenditure", re.I),
}
# (?<![\d.]) so "9.37%" is never read as "37%".
_PCT_RANGE = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d+)?)\s*(?:%|percent)?\s*(?:-|–|to)\s*(\d{1,2}(?:\.\d+)?)\s*(?:%|percent)", re.I)
_PCT_ONE = re.compile(r"(?:~|about|around|approximately|over|more than|at least|of)?\s*(?<![\d.])(\d{1,2}(?:\.\d+)?)\s*(?:%|percent)", re.I)
_WORDS = [
    (r"high[- ]teens", 17, 19), (r"mid[- ]teens", 14, 16), (r"low[- ]teens", 11, 13),
    (r"early[- ]teens", 11, 13), (r"(?:low )?double[- ]digit", 10, 15), (r"high[- ]single[- ]digit", 7, 9),
    (r"mid[- ]single[- ]digit", 4, 6), (r"twenty(?:\s|-)?(?:per ?cent|%)", 20, 20),
]
_CR = re.compile(r"(?:Rs\.?|₹|INR)?\s*(\d[\d,]*(?:\.\d+)?)\s*(crore|crores|cr\b|bn|billion)", re.I)
_FY = re.compile(r"\bFY\s?'?(\d{2,4})\b|\bfiscal\s?(\d{2,4})\b", re.I)
_SEGMENT = re.compile(r"\b(segment|division|vertical|category|this business|that business|EPC|subsidiary|"
                      r"plumbing|paints|adhesives|exports?|domestic business)\b", re.I)
_NOISE = re.compile(r"forward[- ]looking statements|safe harbo|disclaimer|this transcript", re.I)


def _sentences(page: str) -> list[str]:
    flat = re.sub(r"\s+", " ", page)
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+(?=[A-Z])", flat) if 50 <= len(s.strip()) <= 420]


def _value(s: str, metric: str) -> tuple[str, float | None, float | None] | None:
    if metric == "capex":
        m = _CR.search(s)
        if not m:
            return None
        v = float(m.group(1).replace(",", ""))
        if m.group(2).lower() in ("bn", "billion"):
            v *= 100  # ₹bn → ₹ crore
        return m.group(0).strip(), v, v
    m = _PCT_RANGE.search(s)
    if m:
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        if hi - lo <= 15:
            return m.group(0).strip(), lo, hi
    for pat, lo, hi in _WORDS:
        w = re.search(pat, s, re.I)
        if w:
            return w.group(0), lo, hi
    m = _PCT_ONE.search(s)
    if m:
        v = float(m.group(1))
        if 1 <= v <= 60:
            return m.group(0).strip(), v, v
    return None


def _target_fy(s: str, call_fy: int) -> int:
    m = _FY.search(s)
    if m:
        y = int(m.group(1) or m.group(2))
        return y % 100
    by = re.search(r"\bby (?:FY)?(20[2-4]\d)\b", s, re.I)
    if by:
        return int(by.group(1)) % 100
    if re.search(r"next (?:year|fiscal|financial year)", s, re.I):
        return (call_fy + 1) % 100
    return call_fy % 100


def find_promises(pages: list[str], call_fy: int) -> list[dict]:
    """Best candidate statement per metric in one transcript."""
    best: dict[str, tuple[float, dict]] = {}
    for pno, page in enumerate(pages, start=1):
        if pno <= 1:
            continue  # cover page + safe-harbour
        for s in _sentences(page):
            if _NOISE.search(s) or not _CUE.search(s):
                continue
            if re.search(r"\?$|^(?:Can|Could|Would|What|How|Is|Are|Do|Does)\b|\b(?:my|the|next|first|second|"
                         r"last|another|follow-?up) question\b|\bjust wanted to (?:check|understand)\b|"
                         r"^(?:[A-Z][a-z]+ ){1,3}[A-Z][a-z]+:\s*Sir\b|^Sir,", s, re.I):
                continue  # analyst questions are not promises
            if re.search(r"capacity utili[sz]ation|market share", s, re.I):
                continue
            segment = bool(_SEGMENT.search(s))
            for metric, mpat in _METRIC.items():
                if not mpat.search(s):
                    continue
                if metric == "ebitda_margin" and re.search(r"\b(PAT|net|gross)\s+margin", s, re.I):
                    continue
                val = _value(s, metric)
                if not val:
                    continue
                text, lo, hi = val
                score = 1.0
                score += 1.5 if re.search(r"guidance|guide|guiding|target", s, re.I) else 0
                score += 0.8 if _FY.search(s) or re.search(r"this year|next year|full year", s, re.I) else 0
                score += 0.5 if metric != "revenue_growth" or re.search(r"revenue|sales|top[- ]?line|volume", s, re.I) else 0
                score -= 1.0 if re.search(r"\b(last year|previous year|we did|we have done|was|were|grew)\b", s, re.I) else 0
                if metric == "ebitda_margin" and lo is not None and lo > 60:
                    continue
                score -= 0.7 if segment else 0
                cand = {"scope": "segment" if segment else "company", "metric": metric, "quote": s, "page": pno, "value_text": text, "low": lo, "high": hi,
                        "target_fy": _target_fy(s, call_fy)}
                if metric not in best or score > best[metric][0]:
                    best[metric] = (score, cand)
    return [c for sc, c in sorted(best.values(), key=lambda x: -x[0]) if sc >= 2.0]


# ---------------------------------------------------------------- delivered (pure code)


def _fy_of(d: date) -> int:
    return (d.year + 1 if d.month >= 4 else d.year) % 100


def delivered(quarters: list[FinancialPeriod], metric: str, fy: int) -> dict | None:
    """Actuals for fiscal year `fy` so far (or in full), compared like for like with the prior year."""
    cur = [q for q in quarters if _fy_of(q.period_end) == fy]
    if not cur:
        return None
    n = len(cur)
    prev = [q for q in quarters if _fy_of(q.period_end) == (fy - 1) % 100][:n] if n else []
    months = {q.period_end.month for q in cur}
    prev = [q for q in quarters if _fy_of(q.period_end) == (fy - 1) % 100 and q.period_end.month in months]
    span = "full year" if n == 4 else f"{'H1' if n == 2 else f'{n}Q' if n != 1 else 'Q1'} FY{fy:02d}"
    if metric == "revenue_growth":
        a, b = sum(q.revenue or 0 for q in cur), sum(q.revenue or 0 for q in prev)
        if not b or len(prev) != n:
            return None
        return {"value": (a / b - 1) * 100, "unit": "%", "span": span, "complete": n == 4,
                "detail": f"Revenue ₹{a:,.0f} cr vs ₹{b:,.0f} cr in the same period last year"}
    if metric == "ebitda_margin":
        rev, eb = sum(q.revenue or 0 for q in cur), sum(q.ebitda or 0 for q in cur if q.ebitda is not None)
        if not rev or not eb:
            return None
        return {"value": eb / rev * 100, "unit": "%", "span": span, "complete": n == 4,
                "detail": f"EBITDA ₹{eb:,.0f} cr on revenue ₹{rev:,.0f} cr"}
    return None


def verdict(low: float | None, high: float | None, actual: float, complete: bool) -> tuple[GuidanceStatus, str]:
    if low is None:
        return GuidanceStatus.pending, "No numeric target"
    tol = 1.0  # percentage points
    if actual >= low - tol and (high is None or actual <= high + 3):
        return (GuidanceStatus.met if complete else GuidanceStatus.partial,
                "Delivered" if complete else "On track so far")
    if actual > (high or low) + 3:
        return GuidanceStatus.met, "Beat"
    gap = low - actual
    return GuidanceStatus.missed, f"Behind by {gap:.1f} pts" if not complete else f"Missed by {gap:.1f} pts"


# ---------------------------------------------------------------- orchestration


def build_guidance(db: Session, company: Company, max_calls: int = 4) -> int:
    """(Re)extract promises from the last `max_calls` transcripts and score them against actuals."""
    docs = list(db.scalars(select(Document).where(
        Document.company_id == company.id, Document.doc_type == DocType.concall_transcript)
        .order_by(Document.doc_date.desc()).limit(max_calls)))
    quarters = list(db.scalars(select(FinancialPeriod).where(
        FinancialPeriod.company_id == company.id, FinancialPeriod.period_type == PeriodType.quarter)
        .order_by(FinancialPeriod.period_end.desc())))
    # Download the transcripts in parallel: a first look at an unseen ticker is network-bound.
    with ThreadPoolExecutor(max_workers=4) as pool:
        texts = dict(zip([d.id for d in docs], pool.map(lambda d: transcript_pages(d.url), docs)))
    db.execute(delete(GuidanceItem).where(GuidanceItem.company_id == company.id))
    n = 0
    for d in docs:
        pages = texts.get(d.id)
        if not pages:
            d.status = "failed"
            continue
        d.status, d.page_count = "parsed", len(pages)
        call_fy = 2000 + _fy_of(d.doc_date) if d.doc_date else date.today().year
        for p in find_promises(pages, call_fy):
            if p["scope"] == "segment" and p["metric"] != "capex":
                status, actual, evidence = GuidanceStatus.pending, None, {"scope": "segment"}
                assessment = "Segment-level target: company-wide numbers aren't a like-for-like check"
            elif p["metric"] == "capex":
                status, assessment, actual, evidence = GuidanceStatus.pending, "Capex isn't reported quarterly; check the annual cash-flow statement", None, None
            else:
                got = delivered(quarters, p["metric"], p["target_fy"])
                if got is None:
                    status, assessment, actual, evidence = GuidanceStatus.pending, "Too early: no reported quarters for that year yet", None, None
                else:
                    status, assessment = verdict(p["low"], p["high"], got["value"], got["complete"])
                    actual, evidence = got["value"], got
            db.add(GuidanceItem(
                company_id=company.id, document_id=d.id, said_in_period=d.period_label or "",
                metric=p["metric"], guided_value=p["value_text"], guided_low=p["low"], guided_high=p["high"],
                target_period=f"FY{p['target_fy']:02d}", quote=p["quote"], page=p["page"],
                actual_value=actual, status=status, assessment=assessment, evidence=evidence))
            n += 1
    db.commit()
    return n
