"""NSE corporate announcements: fetch → snapshot → parse → classify → prioritise.

Classification is two-stage, for cost:
  1. Rules on NSE's own subject label + the filing text. Free; handles most filings.
  2. Only filings the rules can't place (e.g. "Updates", "General Updates") go to the cheap
     model, ~20 per call, cached. Without an API key, stage 1 still yields a usable feed.
"""

import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.db import utcnow
from app.models import Announcement, Company, IngestionRun
from app.models.enums import AnnouncementCategory as Cat
from app.models.enums import Exchange, Priority
from app.services import llm
from app.services.upsert import upsert_rows

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
SNAPSHOT_DIR = BACKEND_DIR / "snapshots" / "nse"

# ---------------------------------------------------------------- fetch + snapshot


def fetch_nse(symbol: str, start: date, end: date) -> list[dict]:
    s = get_settings()
    r = httpx.get(
        f"{s.nse_base_url}/api/corporate-announcements",
        params={"index": "equities", "symbol": symbol,
                "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")},
        headers={"User-Agent": s.http_user_agent, "Accept": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


def _snapshot_path(symbol: str) -> Path:
    return SNAPSHOT_DIR / f"{symbol}.json"


def load_snapshot(symbol: str) -> list[dict]:
    p = _snapshot_path(symbol)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def save_snapshot(symbol: str, items: list[dict]) -> None:
    """Merge by seq_id so the snapshot only grows."""
    merged = {str(x.get("seq_id")): x for x in load_snapshot(symbol)}
    merged.update({str(x.get("seq_id")): x for x in items})
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    rows = sorted(merged.values(), key=lambda x: x.get("sort_date") or x.get("an_dt") or "", reverse=True)
    _snapshot_path(symbol).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- parse


def _parse_dt(x: dict) -> datetime:
    for key, fmt in (("sort_date", "%Y-%m-%d %H:%M:%S"), ("an_dt", "%d-%b-%Y %H:%M:%S")):
        if x.get(key):
            try:
                return datetime.strptime(x[key], fmt).replace(tzinfo=IST)
            except ValueError:
                pass
    raise ValueError(f"no timestamp in {x.get('seq_id')}")


_BOILER = re.compile(
    r"^.*?\bhas\s+(?:informed|submitted)\s+(?:to\s+)?the\s+Exchange,?\s*"
    r"(?:about|regarding|that|with|the)?\s*", re.I)


def clean_text(text: str) -> str:
    """'X Ltd has informed the Exchange regarding 'Foo'' → 'Foo'."""
    t = _BOILER.sub("", (text or "").strip(), count=1).strip(" .'\"‘’“”")
    t = re.sub(r"\s+", " ", t)
    return t[:1].upper() + t[1:] if t else (text or "").strip()


def parse_nse_item(x: dict, company_id: int) -> dict:
    return {
        "company_id": company_id,
        "exchange": Exchange.NSE,
        "exchange_ref": str(x["seq_id"]),
        "published_at": _parse_dt(x),
        "exchange_category": x.get("desc"),
        "headline": clean_text(x.get("attchmntText") or x.get("desc") or ""),
        "raw_text": x.get("attchmntText"),
        "attachment_url": x.get("attchmntFile") or None,
    }


# ---------------------------------------------------------------- rules


def _has(text: str, *words: str) -> bool:
    """Any of `words` appears at a word start (prefix match: 'acqui' matches 'acquisition')."""
    return any(re.search(rf"(?<!\w){re.escape(w)}", text) for w in words)


CXO = r"(chief executive|ceo|chief financial|cfo|managing director|\bmd\b|whole[- ]time director|chairman|chairperson|chief operating|coo)"

# Base materiality (1–5) per category: how much this kind of filing usually matters.
BASE_MATERIALITY = {
    Cat.results: 4, Cat.m_and_a: 4, Cat.capex: 4, Cat.management_change: 3, Cat.litigation: 3,
    Cat.fund_raise: 3, Cat.credit_rating: 3, Cat.pledging: 3, Cat.bonus_split: 3,
    Cat.insider_trading: 2, Cat.dividend: 2, Cat.earnings_call: 2, Cat.press_release: 2,
    Cat.investor_meetings: 1, Cat.postal_ballot: 1, Cat.agm_egm: 1, Cat.unclassified: 1,
}


def rule_classify(subject: str | None, text: str | None) -> tuple[Cat, int, float] | None:
    """Return (category, materiality 1-5, confidence) or None if the model should decide."""
    s = (subject or "").lower()
    t = (text or "").lower()

    def out(cat: Cat, m: int | None = None, conf: float = 0.9):
        return cat, m if m is not None else BASE_MATERIALITY[cat], conf

    # --- routine paperwork first (cheap to dismiss) ---
    if _has(s, "trading window", "copy of newspaper", "certificate under", "loss of share",
            "duplicate share", "esop", "esos", "esps", "shareholding pattern", "compliance certificate",
            "book closure", "updates on open offer", "statement of deviation", "related party",
            "corrigendum", "monitoring agency", "giving guarantees", "change in auditor",
            "amendment to aoa", "amendment to moa", "options to purchase", "conversion"):
        if "newspaper" in s and _has(t, "financial result"):
            return out(Cat.results, 1)
        return out(Cat.unclassified)
    if "allotment of securities" in s:
        if _has(t, "qip", "qualified institution", "preferential", "rights issue", "debenture",
                "ncd", "commercial paper", "warrant"):
            return out(Cat.fund_raise)
        return out(Cat.unclassified, 1, 0.8)  # usually ESOP allotments

    # --- fund raising (often filed as a board/committee outcome) ---
    fund_words = ("qip", "qualified institution", "preferential issue", "preferential allotment",
                  "rights issue", "capital raise", "raising of funds", "fund raising")
    if _has(s, "qualified institutional placement", "preferential issue", "rights issue"):
        return out(Cat.fund_raise, 4)
    if _has(s, "outcome of board meeting", "committee meeting") and _has(t, *fund_words):
        return out(Cat.fund_raise, 4)

    # --- results ---
    if _has(s, "financial result", "integrated filing- financial", "integrated filing - financial"):
        return out(Cat.results, 4)
    if "outcome of board meeting" in s and _has(t, "financial result", "results for"):
        return out(Cat.results, 4)
    if "board meeting intimation" in s:
        return out(Cat.results, 1) if _has(t, "financial result", "results") else out(Cat.unclassified, 1, 0.7)
    if "investor presentation" in s:
        return out(Cat.results, 2)

    # --- calls & meetings ---
    if _has(s, "analysts/institutional", "analyst", "con. call", "conference call"):
        if _has(t, "transcript"):
            return out(Cat.earnings_call, 2)
        if _has(t, "recording", "audio", "link of"):
            return out(Cat.earnings_call, 1)
        if _has(t, "earnings call", "conference call", "concall") and _has(t, "schedule", "intimation"):
            return out(Cat.earnings_call, 1)
        return out(Cat.investor_meetings, 1)

    # --- management ---
    if "demise" in s:
        return out(Cat.management_change, 2, 0.8)
    if _has(s, "change in management", "change in director", "key managerial", "cessation",
            "resignation", "appointment", "retirement"):
        if _has(t, "auditor", "secretarial", "company secretary", "compliance officer", "registrar"):
            return out(Cat.unclassified, 1, 0.7)
        cxo = bool(re.search(CXO, t)) or "change in management" in s
        return out(Cat.management_change, 4 if cxo else 2, 0.8 if cxo else 0.7)

    # --- corporate actions ---
    if _has(s, "acquisition", "amalgamation", "merger", "scheme of arrangement", "demerger",
            "disinvestment", "sale or disposal"):
        if _has(t, "incorporat", "strike-off", "strike off", "striking off"):
            return out(Cat.m_and_a, 2, 0.85)  # shell subsidiaries: housekeeping, not a deal
        return out(Cat.m_and_a)
    if "agreements" in s or "joint venture" in t:
        return out(Cat.m_and_a, 3, 0.7) if _has(t, "joint venture", "acqui", "share purchase", "stake") else None
    if "credit rating" in s or ("rating" in t and _has(t, "crisil", "icra", "care ratings", "india ratings", "fitch", "moody")):
        if "esg" in t:
            return out(Cat.unclassified, 1, 0.7)
        if _has(t, "downgrade", "negative"):
            return out(Cat.credit_rating, 4)
        if _has(t, "upgrade"):
            return out(Cat.credit_rating, 3)
        return out(Cat.credit_rating, 2)
    if _has(s, "dividend") or ("record date" in s and "dividend" in t):
        return out(Cat.dividend)
    if _has(s, "bonus", "sub-division", "split"):
        return out(Cat.bonus_split)
    if "buyback" in s or "buy back" in s:
        return out(Cat.fund_raise, 4)
    if _has(s, "pledge", "encumbrance"):
        return out(Cat.pledging)
    if _has(s, "insider trading", "takeover", "acquisition of shares", "sast"):
        return out(Cat.insider_trading)
    if "postal ballot" in s:
        return out(Cat.postal_ballot)
    if _has(s, "shareholders meeting", "agm", "egm", "annual general", "extraordinary general"):
        return out(Cat.agm_egm)
    if _has(s, "litigation", "dispute", "penalt", "show cause", "regulatory action",
            "action(s) taken or orders passed", "orders passed"):
        return out(Cat.litigation)
    if "corporate insolvency" in s:
        return out(Cat.litigation, 2, 0.7)  # usually a counterparty's CIRP, not the company's own
    if _has(s, "clarification", "spurt in volume", "news verification", "rumour verification"):
        return out(Cat.press_release, 2, 0.75)
    if "product launch" in s:
        return out(Cat.press_release, 2, 0.8)
    if "committee meeting" in s:
        return out(Cat.unclassified, 1, 0.6)
    if "suspension of trading" in s:
        return out(Cat.unclassified, 1, 0.6)  # typically debt securities maturing
    if _has(s, "fund raising", "raising of funds", "issue of securities"):
        return out(Cat.fund_raise)
    if _has(s, "capacity", "commencement of commercial production"):
        return out(Cat.capex)

    # --- free-text subjects ("Updates", "General Updates", "Press Release"): try keywords ---
    if _has(t, "change in management"):
        return out(Cat.management_change, 3, 0.7)
    if _has(t, "postal ballot"):
        return out(Cat.postal_ballot, 1, 0.8)
    if _has(t, "financial results", "growth momentum") and "press release" in s:
        return out(Cat.results, 3, 0.7)
    if _has(t, "production volume"):
        return out(Cat.press_release, 2, 0.8)
    if _has(t, "commissions", "commissioned"):
        return out(Cat.capex, 3, 0.7)
    if _has(t, "iepf", "investor education and protection", "reclassification from", "dematerialization",
            "dematerialisation"):
        return out(Cat.unclassified, 1, 0.7)
    if _has(t, "analyst(s)/investor(s) meet", "investor conference", "investor meet", "analyst meet",
            "analyst presentation"):
        return out(Cat.investor_meetings, 1, 0.8)
    if _has(t, "earnings presentation", "investor presentation") or re.search(r"update for q[1-4]\s?fy", t):
        return out(Cat.results, 2, 0.75)
    if _has(t, *fund_words):
        return out(Cat.fund_raise, 3, 0.7)
    if _has(t, "commercial paper"):
        return out(Cat.fund_raise, 1, 0.7)
    if re.search(r"\bsales (in|for) (january|february|march|april|may|june|july|august|september|october|november|december)", t):
        return out(Cat.press_release, 3, 0.8)  # monthly volumes (autos) move stocks
    if _has(t, "price increase", "licensing agreement", "license agreement"):
        return out(Cat.press_release, 3, 0.7)
    if _has(t, "incorporation of a subsidiary", "incorporation of wholly", "wholly owned subsidiary"):
        return out(Cat.m_and_a, 2, 0.7)
    if _has(t, "litigation", "antitrust"):
        return out(Cat.litigation, 3, 0.7)
    if _has(t, "business responsibility", "dematerialise", "reconstitution", "committee of the board",
            "intimation under sebi", "general updates", "outcome of board meeting held"):
        return out(Cat.unclassified, 1, 0.5)
    if _has(t, "order", "contract") and _has(t, "bag", "receiv", "win", "award", "secur"):
        return out(Cat.press_release, 3, 0.75)
    if _has(t, "penalty", "show cause", "demand order", "tax demand", "gst", "income tax", "lawsuit",
            "petition", "arbitration", "nclt", "tribunal", "sebi order"):
        return out(Cat.litigation, 3, 0.7)
    if _has(t, "capex", "capacity expansion", "new plant", "greenfield", "brownfield", "commissioning",
            "commercial production"):
        return out(Cat.capex, 3, 0.7)
    if _has(t, "acqui", "joint venture", "amalgamation", "share purchase agreement"):
        return out(Cat.m_and_a, 3, 0.7)
    if _has(t, "esg rating", "change in corporate office", "registered office", "guarantee", "indemnity",
            "investor complaints", "cyber", "website"):
        return out(Cat.unclassified, 1, 0.6)
    return None


def priority_for(materiality: float | None) -> Priority:
    if materiality is None or materiality <= 2:
        return Priority.low
    return Priority.high if materiality >= 4 else Priority.medium


# ---------------------------------------------------------------- LLM stage

LLM_SYSTEM = """You triage Indian stock-exchange (NSE) corporate announcements for a professional investor.
For each filing return:
- category: one of {cats}
- materiality: 1-5. 5 = likely to move the stock (big M&A, CEO/CFO exit, large order vs company size,
  rating downgrade, regulatory action). 1 = routine paperwork. Re-appointments, renewals, approvals of
  something already announced, and vague "disclosure of material information" letters are 2 at most.
- one_liner: <= 18 words, plain English, what happened and why it might matter. No filler like
  "The company has informed". Use only the text given; do not add outside facts.
- person_name / person_role / direction: only for management_change (direction: joining|leaving|redesignated),
  otherwise null.""".format(cats=", ".join(c.value for c in Cat))

LLM_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "category": {"type": "string", "enum": [c.value for c in Cat]},
            "materiality": {"type": "integer"},
            "one_liner": {"type": "string"},
            "person_name": {"type": ["string", "null"]},
            "person_role": {"type": ["string", "null"]},
            "direction": {"type": ["string", "null"]},
        },
        "required": ["id", "category", "materiality", "one_liner", "person_name", "person_role", "direction"],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}


def _llm_batch(db: Session, rows: list[Announcement]) -> dict[str, dict]:
    payload = [
        {"id": str(a.id), "company": a.company.name, "nse_subject": a.exchange_category,
         "text": (a.raw_text or a.headline)[:1200]}
        for a in rows
    ]
    out = llm.complete(
        db, task="classify_announcements", system=LLM_SYSTEM,
        prompt=json.dumps(payload, ensure_ascii=False), schema=LLM_SCHEMA,
        tier="cheap", max_tokens=4000,
    )
    return {it["id"]: it for it in out["items"]}


def classify_pending(db: Session, use_llm: bool = True, batch: int = 20) -> dict:
    """Classify announcements that have no category yet (or were rules-only and an LLM is now
    available for the ambiguous ones)."""
    pending = list(db.scalars(select(Announcement).where(Announcement.processed_at.is_(None))))
    stats = {"rules": 0, "llm": 0, "fallback": 0}
    ambiguous: list[Announcement] = []
    now = utcnow()
    for a in pending:
        r = rule_classify(a.exchange_category, a.raw_text)
        if r is None:
            ambiguous.append(a)
            continue
        cat, m, conf = r
        a.category, a.materiality_score, a.category_confidence = cat, m, conf
        a.priority, a.processed_by_model, a.processed_at = priority_for(m), "rules", now
        stats["rules"] += 1

    llm_ok = use_llm and llm.is_available("cheap")
    for i in range(0, len(ambiguous), batch):
        chunk = ambiguous[i : i + batch]
        results: dict[str, dict] = {}
        if llm_ok:
            try:
                results = _llm_batch(db, chunk)
            except (llm.LLMUnavailable, json.JSONDecodeError, KeyError) as e:
                log.warning("LLM classify failed, falling back to rules: %s", e)
                llm_ok = False
        for a in chunk:
            it = results.get(str(a.id))
            if it:
                cat = Cat(it["category"])
                m = max(1, min(5, int(it["materiality"])))
                a.category, a.materiality_score, a.category_confidence = cat, m, 0.85
                a.one_liner = it["one_liner"]
                if cat == Cat.management_change and it.get("person_name"):
                    a.enrichment = {**(a.enrichment or {}), "person_name": it["person_name"],
                                    "person_role": it.get("person_role"), "direction": it.get("direction")}
                a.processed_by_model = get_settings().llm_cheap_model
                stats["llm"] += 1
            else:
                # Unknown free-text update: keep it visible but low, so nothing is silently lost.
                a.category, a.materiality_score, a.category_confidence = Cat.press_release, 2, 0.4
                a.processed_by_model = "rules-fallback"
                stats["fallback"] += 1
            a.priority, a.processed_at = priority_for(a.materiality_score), now
    db.commit()
    return stats


# ---------------------------------------------------------------- orchestration


def ingest_announcements(
    db: Session, companies: list[Company], days: int = 90, live: bool = True, pause_s: float = 1.0
) -> dict:
    """Fetch (politely, one request per ticker) → snapshot → upsert → classify.
    With live=False, or when NSE fails, the committed snapshot is used instead."""
    run = IngestionRun(source="nse_announcements")
    db.add(run)
    db.flush()
    end = date.today()
    start = end - timedelta(days=days)
    stats: dict = {"live": 0, "snapshot": 0, "failed": [], "rows": 0}
    for c in companies:
        items: list[dict] = []
        if live:
            try:
                items = fetch_nse(c.nse_symbol, start, end)
                save_snapshot(c.nse_symbol, items)
                stats["live"] += 1
            except (httpx.HTTPError, ValueError) as e:
                log.warning("NSE fetch failed for %s: %s", c.nse_symbol, e)
                stats["failed"].append(c.nse_symbol)
            time.sleep(pause_s)
        if not items:
            items = load_snapshot(c.nse_symbol)
            stats["snapshot"] += bool(items)
        rows = []
        for x in items:
            try:
                rows.append(parse_nse_item(x, c.id))
            except (KeyError, ValueError):
                continue
        # Insert new filings only; existing rows keep their classification.
        upsert_rows(db, Announcement, rows, ["exchange", "exchange_ref"], [])
        stats["rows"] += len(rows)
    db.commit()
    stats["classified"] = classify_pending(db)
    run.status, run.stats, run.finished_at = "ok", stats, utcnow()
    db.commit()
    return stats
