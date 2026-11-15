"""The Network: turn "what happened" into "who do I know who can help me understand it".

Everything here is scoped to one investor (owner_id). Results are computed per request and
never written into shared rows (announcements, companies), so one investor's network can't
leak into another's view.

Scoring is plain, explainable arithmetic so every suggestion carries a "why":
    relevance(evidence) × closeness(strength) + small recency bonus
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import utcnow
from app.models import Announcement, Company, Contact, Experience, Person, PersonLink, User
from app.models.enums import Priority
from app.services.normalize import normalize_org_name

TODAY = lambda: utcnow().date()  # noqa: E731


@dataclass
class Suggestion:
    person_id: int
    name: str
    headline: str | None
    relationship: str | None  # None => not a direct contact (reach via `via`)
    strength: int | None
    last_spoke_days: int | None
    score: float
    reasons: list[str] = field(default_factory=list)
    caution: str | None = None  # e.g. current employee: don't ask for non-public information
    via: list[dict] | None = None  # path for second-degree reach

    def dict(self) -> dict:
        return self.__dict__


def _yrs(e: Experience) -> str:
    s = e.start_date.year if e.start_date else "?"
    return f"{s}–{e.end_date.year if e.end_date else 'now'}"


def _load_people(db: Session, owner: User) -> list[Person]:
    return list(db.scalars(
        select(Person).where(Person.owner_id == owner.id)
        .options(selectinload(Person.experiences).selectinload(Experience.company),
                 selectinload(Person.educations), selectinload(Person.expertise),
                 selectinload(Person.contact))))


def _contact_meta(p: Person) -> tuple[str | None, int | None, int | None]:
    c = p.contact
    if c is None:
        return None, None, None
    days = None
    if c.last_interaction_at:
        li = c.last_interaction_at if c.last_interaction_at.tzinfo else c.last_interaction_at.replace(tzinfo=timezone.utc)
        days = (utcnow() - li).days
    return c.relationship_type.value, c.strength, days


def _closeness(strength: int | None, last_days: int | None) -> float:
    s = 0.55 + 0.09 * (strength or 2)  # 0.64 .. 1.0
    if last_days is not None and last_days < 120:
        s += 0.05
    return s


def _theme_words(*texts: str | None) -> set[str]:
    words = set()
    for t in texts:
        for w in re.findall(r"[a-z][a-z&\-]+", (t or "").lower()):
            if len(w) > 3 and w not in {"services", "company", "limited", "india", "and", "the"}:
                words.add(w)
    return words


# ---------------------------------------------------------------- who to call about a company


def who_to_call(db: Session, owner: User, company: Company, limit: int = 3,
                context: str | None = None) -> list[dict]:
    """Rank the investor's contacts for a company: worked there, at a competitor, in the sector,
    or know the theme. Non-contacts are reached through the contact who knows them."""
    people = _load_people(db, owner)
    by_id = {p.id: p for p in people}
    themes = _theme_words(company.industry, company.sector, context)
    out: list[Suggestion] = []
    for p in people:
        best, reasons, caution = 0.0, [], None
        scored: list[tuple[float, str]] = []
        for e in p.experiences:
            co = e.company
            current = e.end_date is None
            if e.company_id == company.id:
                if current:
                    sc, caution = 5.0, "Currently employed there — good for culture and context, not for non-public information."
                    reasons.append(f"Works at {company.name.split(' Ltd')[0]} now ({e.title}, since {e.start_date.year if e.start_date else '?'})")
                else:
                    gap = max(0, TODAY().year - e.end_date.year)
                    sc = max(3.2, 4.8 - 0.2 * gap)
                    reasons.append(f"Ex-{co.name.split(' Ltd')[0] if co else e.org_name}: {e.title}, {_yrs(e)}")
            elif co is not None and co.industry and co.industry == company.industry:
                sc = 3.4 if current else 3.0
                reasons.append(f"{'At' if current else 'Ex-'} competitor {co.name.split(' Ltd')[0]} ({e.title}, {_yrs(e)})")
            elif co is not None and co.sector and co.sector == company.sector:
                sc = 1.6
                reasons.append(f"Same sector: {e.title} at {co.name.split(' Ltd')[0]}")
            else:
                continue
            best = max(best, sc)
            scored.append((sc, reasons[-1]))
        # Every word of the tag must appear ("building materials" must not match "Ship Building").
        tags = [x.theme for x in p.expertise if _theme_words(x.theme) and _theme_words(x.theme) <= themes]
        if tags:
            best = max(best, 2.4) + (0.3 if best >= 2.4 else 0)
            scored.append((2.4, "Knows " + ", ".join(tags[:3])))
        if best == 0:
            continue
        reasons = [r for _, r in sorted(scored, key=lambda x: -x[0])]  # strongest evidence first
        rel, strength, days = _contact_meta(p)
        sug = Suggestion(p.id, p.full_name, p.headline, rel, strength, days, 0.0, reasons[:3], caution)
        if rel is not None:
            sug.score = best * _closeness(strength, days)
        else:
            path = _intro_path(db, owner, p, by_id)
            if not path:
                continue  # we can't reach them
            sug.via = path
            sug.score = best * 0.55 * path[0]["link_strength"]
        out.append(sug)
    out.sort(key=lambda s: -s.score)
    return [s.dict() for s in out[:limit]]


def _intro_path(db: Session, owner: User, target: Person, by_id: dict[int, Person]) -> list[dict] | None:
    links = db.scalars(select(PersonLink).where(
        PersonLink.owner_id == owner.id,
        (PersonLink.person_a_id == target.id) | (PersonLink.person_b_id == target.id))).all()
    best = None
    for l in links:
        other = by_id.get(l.person_b_id if l.person_a_id == target.id else l.person_a_id)
        if other is None or other.contact is None:
            continue
        if best is None or l.strength * other.contact.strength > best[0]:
            best = (l.strength * other.contact.strength, other, l)
    if not best:
        return None
    _, other, l = best
    return [{"person_id": other.id, "name": other.full_name, "relationship": other.contact.relationship_type.value,
             "link_strength": l.strength, "evidence": l.evidence}]


# ---------------------------------------------------------------- people named in filings


_GENERIC_ORGS = {"independent", "self-employed", "freelance", "family office", "consultant"}


def _specific_org(e: Experience) -> bool:
    """Only distinctive employer names count as evidence ('Independent' matches 'Independent Director')."""
    n = (e.org_name or "").strip().lower()
    return bool(n) and n not in _GENERIC_ORGS and (e.company_id is not None or len(n.split()) >= 2)


def _years_in(text: str, anchor: str) -> list[int]:
    """Years mentioned within ~80 chars of `anchor` in `text` (e.g. 'a 2017 graduate of X')."""
    yrs = []
    for m in re.finditer(re.escape(anchor), text, re.I):
        window = text[max(0, m.start() - 80): m.end() + 80]
        yrs += [int(y) for y in re.findall(r"\b(19[6-9]\d|20[0-4]\d)\b", window)]
    return yrs


def connections_for_person(db: Session, owner: User, company: Company, person: dict,
                           filing_text: str | None) -> list[dict]:
    """Who in the network has worked with, studied with, or sits one hop from a person in a filing.

    Evidence is inferred, never assumed:
      * same company with overlapping tenure  -> likely worked together
      * an org / school named in the filing that a contact also attended (and years overlap)
      * a contact who knows such a person (person_links) -> second-degree
    """
    text = filing_text or ""
    flat = re.sub(r"\s+", " ", text)
    people = _load_people(db, owner)
    by_id = {p.id: p for p in people}
    fn = (person.get("role") or "").lower()
    out: list[Suggestion] = []
    for p in people:
        reasons, score = [], 0.0
        for e in p.experiences:
            if e.company_id == company.id:
                overlap = e.end_date is None or (e.end_date.year >= TODAY().year - 3)
                same_fn = e.function and any(w in fn for w in e.function.split())
                sc = 4.0 if overlap else 3.0
                sc += 0.6 if same_fn else 0
                score = max(score, sc)
                reasons.append(
                    f"{'Works' if e.end_date is None else 'Worked'} at {company.name.split(' Ltd')[0]} "
                    f"({e.title}, {_yrs(e)})" + (" — same function" if same_fn else ""))
            elif _specific_org(e) and re.search(rf"\b{re.escape(e.org_name)}\b", flat, re.I):
                score = max(score, 3.4)
                reasons.append(f"Was at {e.org_name} ({_yrs(e)}), which the filing names in {person['name']}'s background")
        for ed in p.educations:
            if re.search(rf"\b{re.escape(ed.institution)}\b", flat, re.I):
                yrs = _years_in(flat, ed.institution)
                overlap = any((ed.start_year or 0) <= y <= (ed.end_year or 0) + 1 for y in yrs)
                score = max(score, 3.8 if overlap else 2.6)
                reasons.append(
                    f"{ed.institution} {ed.start_year}–{ed.end_year}"
                    + (f"; filing says {person['name'].split()[-1]} graduated {yrs[0]} — likely overlapped" if overlap and yrs
                       else "; same school"))
        if not reasons:
            continue
        rel, strength, days = _contact_meta(p)
        sug = Suggestion(p.id, p.full_name, p.headline, rel, strength, days, 0.0, reasons[:2])
        if rel is not None:
            sug.score = score * _closeness(strength, days)
        else:
            path = _intro_path(db, owner, p, by_id)
            if not path:
                continue
            sug.via, sug.score = path, score * 0.55 * path[0]["link_strength"]
        out.append(sug)
    out.sort(key=lambda s: -s.score)
    return [s.dict() for s in out[:3]]


# ---------------------------------------------------------------- expertise + keep warm


def expertise(db: Session, owner: User, theme: str, limit: int = 6) -> list[dict]:
    q = _theme_words(theme) or {theme.lower()}
    out: list[Suggestion] = []
    for p in _load_people(db, owner):
        reasons, score = [], 0.0
        # Full-phrase matches count most; a single shared word ("specialty") counts a little.
        hits = []
        for x in p.expertise:
            frac = len(_theme_words(x.theme) & q) / len(q)
            if theme.lower() in x.theme.lower() or frac == 1:
                hits.append((3.0, x.theme))
            elif frac >= 0.5:
                hits.append((1.0, x.theme))
        if hits:
            hits.sort(reverse=True)
            score += hits[0][0] + 0.4 * (len(hits) - 1)
            reasons.append("Known for " + ", ".join(t for _, t in hits[:3]))
        for e in p.experiences:
            co = e.company
            if co and (_theme_words(co.industry, co.sector) & q):
                score += 1.2
                reasons.append(f"{e.title} at {co.name.split(' Ltd')[0]} ({_yrs(e)})")
        if not score:
            continue
        rel, strength, days = _contact_meta(p)
        sug = Suggestion(p.id, p.full_name, p.headline, rel, strength, days,
                         score * (_closeness(strength, days) if rel else 0.5), reasons[:3])
        out.append(sug)
    out.sort(key=lambda s: -s.score)
    return [s.dict() for s in out[:limit]]


def keep_warm(db: Session, owner: User, quiet_days: int = 120, event_days: int = 21) -> list[dict]:
    """Contacts you haven't spoken to in a while whose current/former employer just had news:
    a natural reason to reconnect."""
    since = utcnow() - timedelta(days=event_days)
    out = []
    for p in _load_people(db, owner):
        rel, strength, days = _contact_meta(p)
        if rel is None or (days is not None and days < quiet_days):
            continue
        cids = {e.company_id for e in p.experiences if e.company_id}
        if not cids:
            continue
        ann = db.scalars(
            select(Announcement).where(Announcement.company_id.in_(cids), Announcement.published_at >= since,
                                       Announcement.priority.in_([Priority.high, Priority.medium]))
            .order_by(Announcement.materiality_score.desc(), Announcement.published_at.desc()).limit(1)).first()
        if ann is None:
            continue
        e = next(x for x in p.experiences if x.company_id == ann.company_id)
        out.append({
            "person_id": p.id, "name": p.full_name, "headline": p.headline, "relationship": rel,
            "strength": strength, "last_spoke_days": days,
            "hook": f"{ann.company.name.split(' Ltd')[0]} ({'their employer' if e.end_date is None else 'their ex-employer'}): "
                    f"{ann.one_liner or ann.headline}",
            "announcement_id": ann.id, "symbol": ann.company.nse_symbol,
            "category": ann.category.value if ann.category else None,
        })
    out.sort(key=lambda x: -(x["last_spoke_days"] or 0))
    return out


def person_card(db: Session, owner: User, person_id: int) -> dict | None:
    p = db.scalar(select(Person).where(Person.id == person_id, Person.owner_id == owner.id)
                  .options(selectinload(Person.experiences), selectinload(Person.educations),
                           selectinload(Person.expertise), selectinload(Person.contact)))
    if p is None:
        return None
    rel, strength, days = _contact_meta(p)
    return {
        "id": p.id, "name": p.full_name, "headline": p.headline, "location": p.location,
        "source": p.source.value, "relationship": rel, "strength": strength, "last_spoke_days": days,
        "how_met": p.contact.how_met if p.contact else None,
        "experiences": [{"org": e.org_name, "title": e.title, "years": _yrs(e),
                         "symbol": e.company.nse_symbol if e.company else None}
                        for e in sorted(p.experiences, key=lambda e: e.start_date or date.min, reverse=True)],
        "educations": [{"institution": x.institution, "degree": x.degree, "years": f"{x.start_year}–{x.end_year}"}
                       for x in p.educations],
        "expertise": [x.theme for x in p.expertise],
        "path": None if rel else _intro_path(db, owner, p, {q.id: q for q in _load_people(db, owner)}),
    }


def match_company(db: Session, org: str) -> Company | None:
    """Link a free-text employer to a listed company by normalised-name prefix."""
    n = normalize_org_name(org)
    if not n:
        return None
    for c in db.scalars(select(Company)):
        cn = c.name_normalized
        if cn == n or cn.startswith(n + " ") or n.startswith(cn + " "):
            return c
    return None
