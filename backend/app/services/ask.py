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


def _find_company(db: Session, text: str) -> Company | None:
    t = text.upper()
    companies = list(db.scalars(select(Company)))
    for c in companies:  # exact ticker
        if c.nse_symbol and re.search(rf"(?<![A-Z]){re.escape(c.nse_symbol)}(?![A-Z])", t):
            return c
    n = normalize_org_name(text)
    for c in sorted(companies, key=lambda c: -len(c.name_normalized)):
        first = c.name_normalized.split()[0]
        if c.name_normalized in n or (len(first) > 4 and re.search(rf"\b{re.escape(first)}\b", n)):
            return c
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
    if company and re.search(r"who|call|ask|talk|speak|expert|know", low):
        return {"type": "who_to_call", "title": f"Who to call about {company.name.split(' Ltd')[0]}",
                "symbol": company.nse_symbol, "results": network.who_to_call(db, user, company, limit=5)}
    if company:
        return {"type": "company", "title": company.name, "symbol": company.nse_symbol}

    m = re.search(r"(?:who (?:knows|understands|can explain|is good on|covers)|expert(?:s|ise)? (?:on|in)|"
                  r"go-?to (?:people|person) for|ask about)\s+(.+?)[?.]*$", low)
    theme = m.group(1) if m else None
    if not theme:  # a bare theme that matches someone's expertise
        tags = {t.lower() for t in db.scalars(select(Expertise.theme))}
        theme = next((t for t in tags if t in low), None)
    if theme:
        theme = re.sub(r"^(the|about)\s+", "", theme.strip())
        return {"type": "expertise", "title": f"Your go-to people for {theme}",
                "results": network.expertise(db, user, theme)}

    sym = re.fullmatch(r"(?:research\s+)?([A-Za-z&]{2,15})", text)
    if sym:  # possibly an NSE ticker we haven't seen yet: the research view resolves it lazily
        return {"type": "company", "title": sym.group(1).upper(), "symbol": sym.group(1).upper()}

    return {"type": "help", "title": "Try one of these", "examples": EXAMPLES}
