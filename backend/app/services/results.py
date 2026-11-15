"""Results card: attach the headline numbers (Revenue/EBITDA/PBT/PAT, QoQ + YoY) to each
results filing. Numbers come from the standardised financials; arithmetic is code, not a model."""

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Announcement, FinancialPeriod
from app.models.enums import AnnouncementCategory, PeriodType
from app.services.fundamentals import headline_compare

_PERIOD = re.compile(
    r"(?:period|quarter(?: and (?:half year|nine months|year))?)\s+ended\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(\d{4})", re.I)
_MONTH = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


_PERIOD_US = re.compile(  # NSE's own wording: "period ended September 30, 2026"
    r"(?:period|quarter(?: and (?:half year|nine months|year))?)\s+ended\s+(?:on\s+)?"
    r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I)


def period_from_text(text: str | None) -> date | None:
    m = _PERIOD.search(text or "")
    if m and _MONTH.get(m.group(2).lower()):
        return date(int(m.group(3)), _MONTH[m.group(2).lower()], int(m.group(1)))
    m = _PERIOD_US.search(text or "")
    if m and _MONTH.get(m.group(1).lower()):
        return date(int(m.group(3)), _MONTH[m.group(1).lower()], int(m.group(2)))
    return None


def _infer_period(published: date) -> date:
    """Results filed in Oct/Nov are for the quarter ended Sep, etc."""
    for qend in (date(published.year, 12, 31), date(published.year, 9, 30), date(published.year, 6, 30),
                 date(published.year, 3, 31), date(published.year - 1, 12, 31)):
        if qend < published:
            return qend
    return date(published.year - 1, 12, 31)


def enrich_results(db: Session, company_id: int | None = None) -> int:
    q = select(Announcement).where(Announcement.category == AnnouncementCategory.results,
                                   Announcement.materiality_score >= 3)
    if company_id:
        q = q.where(Announcement.company_id == company_id)
    n = 0
    for a in db.scalars(q):
        quarters = list(db.scalars(
            select(FinancialPeriod).where(FinancialPeriod.company_id == a.company_id,
                                          FinancialPeriod.period_type == PeriodType.quarter)
            .order_by(FinancialPeriod.period_end.desc())))
        if not quarters:
            continue
        target = period_from_text(a.raw_text) or _infer_period(a.published_at.date())
        idx = next((i for i, p in enumerate(quarters) if p.period_end == target), None)
        if idx is None:
            continue  # financials not yet updated for this quarter: don't show stale numbers
        cmp = headline_compare(quarters, idx)
        if cmp:
            a.enrichment = {**(a.enrichment or {}), "results": cmp}
            n += 1
    db.commit()
    return n
