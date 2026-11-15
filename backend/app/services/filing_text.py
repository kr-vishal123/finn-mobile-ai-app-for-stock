"""Read the actual filing PDF and pull out what the card needs.

Rules first (names, roles, direction, the "brief profile" annexure that SEBI requires for
appointments, the key sentence of an M&A/capex filing). When a model key is configured,
the cheap model can refine this; the card works either way.
"""

import hashlib
import io
import logging
import re

import httpx
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.models import Announcement
from app.models.enums import AnnouncementCategory as Cat
from app.models.enums import Priority

log = logging.getLogger(__name__)
CACHE = BACKEND_DIR / "data" / "pdf"


def pdf_text(url: str, max_pages: int = 8) -> str | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".txt")
    if f.exists():
        return f.read_text(encoding="utf-8")
    try:
        r = httpx.get(url, headers={"User-Agent": get_settings().http_user_agent},
                      timeout=60, follow_redirects=True)
        r.raise_for_status()
        reader = PdfReader(io.BytesIO(r.content))
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:max_pages])
    except Exception as e:  # network, encrypted or malformed PDFs: degrade to the headline
        log.warning("pdf fetch/parse failed %s: %s", url, e)
        return None
    text = re.sub(r"[ \t]+", " ", text)
    f.write_text(text, encoding="utf-8")
    return text


_NAME = re.compile(
    r"\b(?:Mr|Ms|Mrs|Dr|Shri|Smt|Prof)\.?\s+"
    r"([A-Z][A-Za-z'’\-]*\.?(?:\s?[A-Z][A-Za-z'’\-]*\.?){1,4})")
_ROLE = re.compile(
    r"(Chief [A-Z][a-z]+(?: [A-Z][a-z]+)? Officer|Managing Director(?: (?:&|and) (?:CEO|Chief Executive Officer))?|"
    r"CEO|CFO|COO|Whole[- ]?time Director|Executive Director|Independent Director|"
    r"Non[- ]Executive[,]? Non[- ]Independent Director|Vice[- ]Chairman|Chairman|Chairperson|"
    r"Company Secretary|Group Head\s?[–-]\s?[A-Za-z ,&]+?(?= and| of|\.|,)|President[A-Za-z ,–-]{0,40}|"
    r"Senior Management Personnel)", re.I)
_JOIN = re.compile(r"appoint|assum(?:ed|es) (?:the )?office|designated|elevat|re-?designat|join", re.I)
_LEAVE = re.compile(r"resign|retire|superannuat|ceas|step(?:ped|s)? down|demise|relinquish", re.I)
_SIGNOFF = re.compile(r"\b(Yours (?:faithfully|truly|sincerely)|Thanking you|For [A-Z][A-Za-z ]+ Limited\s*$)", re.I | re.M)
_KEY_WORDS = {
    Cat.m_and_a: r"acqui|joint venture|amalgamat|merger|demerger|stake|share purchase|subscription",
    Cat.capex: r"capacity|plant|commission|commercial production|capex|expansion|MW|tonnes",
    Cat.fund_raise: r"QIP|qualified institution|preferential|allot|raise|issue price|debenture",
    Cat.litigation: r"order|penalty|demand|court|tribunal|petition|show cause|SEBI|tax",
    Cat.press_release: r"order|contract|launch|partner|agreement",
}


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z0-9(])", flat) if 40 < len(s.strip()) < 600]


def _body(text: str) -> str:
    """The letter body: after the 'Sub:' line, before the sign-off (drops letterhead + signatory)."""
    flat = re.sub(r"\s+", " ", text)
    start = re.search(r"\b(Sub(?:ject)?\s*:|Dear Sir)", flat)
    flat = flat[start.start():] if start else flat
    end = _SIGNOFF.search(flat)
    return flat[: end.start()] if end else flat


def extract_management(text: str) -> list[dict]:
    """People named in a management-change letter, with role, direction and profile."""
    body = _body(text)
    flat_all = re.sub(r"\s+", " ", text)
    people: dict[str, dict] = {}
    for m in _NAME.finditer(body):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .")
        if len(name.split()) < 2:
            continue
        # Context: the person's own sentence decides direction (a neighbour's "resigned" must not leak in).
        lo = max(body.rfind(". ", 0, m.start()) + 2, m.start() - 300, 0)
        hi = body.find(". ", m.end())
        hi = len(body) if hi == -1 else min(hi + 1, m.end() + 300)
        ctx = body[lo:hi]
        after = body[m.end(): m.end() + 260]
        role = _ROLE.search(after) or _ROLE.search(ctx)
        direction = "leaving" if _LEAVE.search(ctx) else "joining" if _JOIN.search(ctx) else None
        key = name.lower().split()[-1] + name.lower().split()[0][:1]
        cur = people.get(key)
        if cur is None or (cur["role"] is None and role) or (cur["direction"] is None and direction):
            people[key] = {"name": name, "role": role.group(1).strip() if role else (cur or {}).get("role"),
                           "direction": direction or (cur or {}).get("direction")}
    out = [p for p in people.values() if p["direction"]]
    for p in out:
        if p["role"]:
            p["role"] = re.sub(r"\s+\w$", "", p["role"]).strip(" ,–-")
        p["profile"] = _profile(flat_all, p["name"]) if p["direction"] == "joining" else None
    return out


def _profile(flat: str, name: str) -> str | None:
    """SEBI annexures carry a brief profile for appointees. Anchor on the person's own bio
    sentence ("Mr. X has/is/holds ...") so profiles never bleed across people. Verbatim."""
    first, last = re.escape(name.split()[0].rstrip(".")), re.escape(name.split()[-1])
    verbs = r"\s+(?:has|is|holds|was|brings|joined|began|started|comes|served|led|headed)\b"
    pat = rf"(?:(?:(?:Mr|Ms|Mrs|Dr)\.?\s+)?{first}[A-Za-z.\s]{{0,25}}|(?:Mr|Ms|Mrs|Dr)\.?\s+){last}{verbs}"
    for m in re.finditer(pat, flat):
        chunk = flat[m.start(): m.start() + 700]
        if re.search(r"not related|is related to|relationship|debarred|is appointed|appointed as|"
                     r"with effect from|not disqualified|liable to retire", chunk[:150], re.I):
            continue
        sents = re.split(r"(?<=\.)\s+(?=[A-Z])", chunk)
        bio = " ".join(sents[:3]).strip()
        if len(bio) > 60:
            return bio[:600]
    return None


_BOILER = re.compile(r"Regulation 30|Listing Obligations|Schedule III|Master Circular|Dear Sir|enclos|herewith|"
                     r"Please find|for your (?:information|records)|intimat", re.I)


def subject_line(text: str) -> str | None:
    """The letter's own 'Re:' / 'Sub:' line usually *is* the news ('L&T bags order from Noida Metro')."""
    flat = re.sub(r"\s+", " ", text)
    for m in re.finditer(r"\b(?:Re|Sub(?:ject)?)\s?:\s*(.{20,220}?)(?=\s+(?:We |Please |Dear |Ref|Pursuant|In terms|With reference|This is)|$)", flat):
        s = m.group(1).strip(" .-–")
        if not _BOILER.search(s) and not re.search(r"Disclosure under|Intimation under|Outcome of", s, re.I):
            return s
    return None


def key_sentence(text: str, cat: Cat) -> str | None:
    pat = _KEY_WORDS.get(cat)
    if not pat:
        return None
    for s in _sentences(_body(text)):
        if re.search(pat, s, re.I) and not _BOILER.search(s):
            return s[:320]
    return None


def enrich_filings(db: Session, categories=(Cat.management_change, Cat.m_and_a, Cat.capex,
                                           Cat.fund_raise, Cat.litigation, Cat.press_release)) -> dict:
    """Read the PDFs of material filings once; store what the card needs in `enrichment`."""
    stats = {"read": 0, "people": 0, "key": 0, "reclassified": 0}
    q = select(Announcement).where(Announcement.category.in_(categories),
                                   Announcement.priority.in_([Priority.high, Priority.medium]),
                                   Announcement.attachment_url.is_not(None))
    for a in db.scalars(q):
        if (a.enrichment or {}).get("pdf_read"):
            continue
        text = pdf_text(a.attachment_url)
        if not text:
            continue
        stats["read"] += 1
        # Public filing text, kept so person-matching works without re-downloading the PDF.
        enr = {**(a.enrichment or {}), "pdf_read": True, "text_excerpt": re.sub(r"\s+", " ", text)[:8000]}
        if a.category == Cat.management_change:
            if re.search(r"Regulation 30\s*\(5\)", text) and not _LEAVE.search(_body(text)):
                # A list of who may make disclosures, not a change at the top.
                a.category, a.materiality_score, a.priority = Cat.unclassified, 1, Priority.low
                stats["reclassified"] += 1
            else:
                people = extract_management(text)
                if people:
                    enr["people"] = people
                    stats["people"] += len(people)
                    lead = people[0]
                    verb = "joins as" if lead["direction"] == "joining" else "leaves as"
                    a.one_liner = a.one_liner or f"{lead['name']} {verb} {lead['role'] or 'senior management'}" + (
                        f" (+{len(people) - 1} more)" if len(people) > 1 else "")
                    senior = any(p["role"] and re.search(
                        r"chief|managing|ceo|cfo|chair|whole|executive director", p["role"], re.I) for p in people)
                    if not senior and a.materiality_score and a.materiality_score >= 4:
                        a.materiality_score, a.priority = 3, Priority.medium  # mid-level SMP changes
        else:
            subj = subject_line(text)
            if subj and (a.one_liner is None or a.processed_by_model in ("rules", "rules-fallback")):
                a.one_liner = subj  # the filing's own subject beats a generic exchange label
                size = re.search(r"\b(ultra-?mega|mega|major|large|significant)\*?", subj, re.I)
                if size:  # companies like L&T grade their own orders; use their scale
                    m = {"ultra-mega": 4, "ultramega": 4, "mega": 4, "major": 3, "large": 3, "significant": 2}[size.group(1).lower()]
                    a.materiality_score = m
                    a.priority = Priority.high if m >= 4 else Priority.medium if m == 3 else Priority.low
            ks = key_sentence(text, a.category)
            if ks and (not subj or subj.lower()[:40] not in ks.lower()):
                enr["key_sentence"] = ks
                stats["key"] += 1
            else:
                enr.pop("key_sentence", None)
        a.enrichment = enr
    db.commit()
    return stats
