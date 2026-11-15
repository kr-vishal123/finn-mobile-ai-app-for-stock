"""Ask FINN: one input box, routed to the right tool.

The router is deterministic (patterns + a lookup of company names, people and themes) so it
is instant and free; a cheap model can take over intent parsing when a key is configured.
Every answer is a structured result the UI renders as cards, not a wall of generated text.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Announcement, Company, Expertise, Person, User
from app.models.enums import AnnouncementCategory
from app.services import network
from app.services.normalize import normalize_org_name, normalize_person_name

EXAMPLES = [
    "Who should I call about ASTRAL?",
    "Who knows specialty chemicals?",
    "Who can introduce me to Prithvi Vachani?",
    "Research DIXON",
    "Who should I reconnect with?",
]


_GENERIC = {"india", "ltd", "limited", "company", "the", "and", "of", "co"}
_INTENT = {"who", "whom", "should", "i", "we", "call", "about", "research", "can", "could", "ask", "talk", "to",
           "speak", "with", "the", "me", "tell", "on", "for", "is", "open", "show", "analyse", "analyze",
           "company", "stock", "shares", "share", "what", "how", "regarding", "know", "knows", "expert",
           "please", "a", "an", "in", "at", "look", "deep", "dive", "into", "of", "do"}


def _find_company(db: Session, text: str) -> Company | None:
    """A company already in FINN's DB: exact ticker, or *every* distinctive word of its name.
    ("Adani" alone must not match Adani Green when the user means Adani Power.)"""
    t = text.upper()
    companies = list(db.scalars(select(Company)))
    for c in companies:  # exact ticker
        if c.nse_symbol and re.search(rf"(?<![A-Z]){re.escape(c.nse_symbol)}(?![A-Z])", t):
            return c
    q = set(normalize_org_name(text).split())
    best, best_n = None, 0
    for c in companies:
        sig = [w for w in c.name_normalized.split() if w not in _GENERIC]
        if sig and all(w in q for w in sig) and len(sig) > best_n:
            best, best_n = c, len(sig)
    return best


# Market shorthand that a name search gets wrong ("L&T" would otherwise resolve to L&T Finance).
_ALIASES = {
    "l&t": ("LT", "Larsen & Toubro Ltd"), "lnt": ("LT", "Larsen & Toubro Ltd"), "larsen": ("LT", "Larsen & Toubro Ltd"),
    "m&m": ("M&M", "Mahindra & Mahindra Ltd"), "hul": ("HINDUNILVR", "Hindustan Unilever Ltd"),
    "sbi": ("SBIN", "State Bank of India"), "ril": ("RELIANCE", "Reliance Industries Ltd"),
    "reliance": ("RELIANCE", "Reliance Industries Ltd"), "itc": ("ITC", "ITC Ltd"),
}


def _search_symbol(text: str) -> tuple[str, str] | None:
    """Resolve a company *name* to an NSE ticker via screener's search (any listed company)."""
    import httpx

    from app.config import get_settings

    words = [w for w in re.findall(r"[A-Za-z0-9&.\-]+", text) if w.lower() not in _INTENT]
    if not words:
        return None
    alias = _ALIASES.get(" ".join(words).lower())
    if alias:
        return alias
    s = get_settings()
    try:
        r = httpx.get(f"{s.screener_base_url}/api/company/search/", params={"q": " ".join(words)},
                      headers={"User-Agent": s.http_user_agent}, timeout=15)
        r.raise_for_status()
        hits = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    for h in hits:
        m = re.match(r"/company/([A-Z0-9&\-]*[A-Z][A-Z0-9&\-]*)/", h.get("url", ""))  # NSE tickers have letters
        if m:
            return m.group(1), h.get("name") or m.group(1)
    return None


def _filing_people(db: Session) -> list[tuple[dict, Announcement]]:
    out = []
    for a in db.scalars(select(Announcement).where(Announcement.category == AnnouncementCategory.management_change)):
        for p in (a.enrichment or {}).get("people", []):
            out.append((p, a))
    return out


def _find_person(db: Session, user: User, text: str):
    n = normalize_person_name(text)
    for p, a in _filing_people(db):
        last = normalize_person_name(p["name"]).split()[-1]
        if len(last) > 2 and re.search(rf"\b{re.escape(last)}\b", n):
            return "filing", p, a
    for p in db.scalars(select(Person).where(Person.owner_id == user.id)):
        if p.name_normalized in n or (len(p.name_normalized.split()[-1]) > 3 and p.name_normalized.split()[-1] in n.split()):
            return "network", p, None
    return None


def _is_question(low: str) -> bool:
    """A question *about the business* (not 'who should I call'): goes to transcript Q&A."""
    if re.search(r"\bwho\b|\bcall\b|introduc|reconnect", low):
        return False
    return bool(re.search(r"\b(what|why|how|did|does|is there|any)\b.*\b(say|said|says|outlook|plan|plans|guid\w*|"
                          r"margin\w*|capex|demand|pricing|prices?|expect\w*|growth|debt|order\w*|"
                          r"competition|risk\w*|strategy|target\w*)\b", low))


def _company_qa(db: Session, company: Company, text: str) -> dict:
    from app.services.qa import ask_company
    r = ask_company(db, company, text)
    if r["mode"] == "none":  # no transcripts yet: open the research view, which fetches them
        return {"type": "company", "title": company.name, "symbol": company.nse_symbol}
    return {"type": "company_qa", "title": company.name.split(" Ltd")[0], "symbol": company.nse_symbol, "qa": r}


def answer(db: Session, user: User, q: str) -> dict:
    text = q.strip()
    low = text.lower()

    if re.search(r"reconnect|haven'?t (?:spoken|talked)|keep (?:in touch|warm)|catch up", low):
        return {"type": "keep_warm", "title": "Worth a call this week",
                "results": network.keep_warm(db, user)}

    if re.search(r"introduc|who knows|reach|connect(?:ed)? (?:me )?(?:to|with)|know anyone who knows", low):
        hit = _find_person(db, user, text)
        if hit and hit[0] == "filing":
            _, p, a = hit
            return {"type": "person_reach", "title": f"Paths to {p['name']}",
                    "person": {**p, "company": a.company.name, "symbol": a.company.nse_symbol,
                               "filing_url": a.attachment_url, "filed": a.published_at.isoformat()},
                    "results": network.connections_for_person(db, user, a.company, p, (a.enrichment or {}).get("text_excerpt"))}
        if hit and hit[0] == "network":
            return {"type": "person", "title": hit[1].full_name,
                    "person": network.person_card(db, user, hit[1].id)}

    company = _find_company(db, text)
    if company and _is_question(low):
        return _company_qa(db, company, text)
    if company and re.search(r"who|call|ask|talk|speak|expert|know", low):
        return {"type": "who_to_call", "title": f"Who to call about {company.name.split(' Ltd')[0]}",
                "symbol": company.nse_symbol, "results": network.who_to_call(db, user, company, limit=5)}
    if company:
        return {"type": "company", "title": company.name, "symbol": company.nse_symbol}

    m = re.search(r"(?:who (?:knows|understands|can explain|is good on|covers)|expert(?:s|ise)? (?:on|in)|"
                  r"go-?to (?:people|person) for|ask about)\s+(.+?)[?.]*$", low)
    theme = m.group(1) if m else None
    if not theme:  # a bare theme: only when the whole query *is* the theme ("power" ≠ "adani power")
        tags = {t.lower() for t in db.scalars(select(Expertise.theme))}
        bare = " ".join(w for w in re.findall(r"[a-z&\-]+", low) if w not in _INTENT)
        theme = bare if bare in tags else None
    if theme:
        theme = re.sub(r"^(the|about)\s+", "", theme.strip())
        return {"type": "expertise", "title": f"Your go-to people for {theme}",
                "results": network.expertise(db, user, theme)}

    # Not in FINN yet: resolve the name to a ticker (any NSE company), then answer the same way.
    found = _search_symbol(text)
    if found:
        symbol, name = found
        if _is_question(low):
            from app.services.companies import ensure_company
            c = ensure_company(db, symbol)
            if c is not None:
                return _company_qa(db, c, text)
        if re.search(r"who|call|ask|talk|speak|expert|know", low):
            from app.services.companies import ensure_company
            c = ensure_company(db, symbol)
            if c is not None:
                return {"type": "who_to_call", "title": f"Who to call about {name.split(' Ltd')[0]}",
                        "symbol": symbol, "results": network.who_to_call(db, user, c, limit=5)}
        return {"type": "company", "title": name, "symbol": symbol}

    sym = re.fullmatch(r"(?:research\s+)?([A-Za-z&]{2,15})", text.strip())
    if sym:  # looks like a ticker: the research view resolves it lazily
        return {"type": "company", "title": sym.group(1).upper(), "symbol": sym.group(1).upper()}

    return {"type": "help", "title": "Try one of these", "examples": EXAMPLES}
