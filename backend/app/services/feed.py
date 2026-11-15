"""The windowed digest: everything that happened across the portfolio, most important first."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import Feed, FeedItem, RoutineGroup, SignalItem
from app.db import utcnow
from app.models import Alert, Announcement, Company, User, WatchlistItem
from app.models.enums import Priority, WatchlistKind
from app.services import network

_PRIO_RANK = {Priority.high: 0, Priority.medium: 1, Priority.low: 2, None: 3}


def _aware(dt: datetime) -> datetime:
    """SQLite drops tzinfo; everything we store is UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _portfolio_ids(db: Session, user: User):
    return select(WatchlistItem.company_id).where(
        WatchlistItem.user_id == user.id, WatchlistItem.kind == WatchlistKind.portfolio)


_PUBLIC_ENRICHMENT = ("results", "people", "key_sentence")
_NETWORKED = {"management_change", "m_and_a", "capex", "litigation", "fund_raise"}


def _item(a: Announcement) -> FeedItem:
    enr = {k: v for k, v in (a.enrichment or {}).items() if k in _PUBLIC_ENRICHMENT} or None
    return FeedItem(
        id=a.id, symbol=a.company.nse_symbol, company_name=a.company.name,
        published_at=_aware(a.published_at), category=a.category, priority=a.priority,
        materiality=a.materiality_score, headline=a.headline, one_liner=a.one_liner,
        exchange_category=a.exchange_category, attachment_url=a.attachment_url,
        enrichment=enr,
    )


def attach_network(db: Session, user: User, a: Announcement, item: FeedItem) -> FeedItem:
    """Who in *this user's* network can help with this filing. Never stored on the shared row."""
    cat = a.category.value if a.category else ""
    if cat not in _NETWORKED or a.priority not in (Priority.high, Priority.medium):
        return item
    people = (a.enrichment or {}).get("people") or []
    if cat == "management_change" and people:
        text = (a.enrichment or {}).get("text_excerpt")
        out = []
        for p in people[:3]:
            conns = network.connections_for_person(db, user, a.company, p, text)
            if conns:
                out.append({"for": p["name"], "results": conns[:2]})
        item.network = out or None
    else:
        sug = network.who_to_call(db, user, a.company, limit=2, context=cat.replace("_", " "))
        item.network = [{"for": None, "results": sug}] if sug else None
    return item


def build_feed(db: Session, user: User, hours: int = 24, now: datetime | None = None) -> Feed:
    now = now or utcnow()
    pids = _portfolio_ids(db, user)
    since = now - timedelta(hours=hours)
    note = None

    in_window = db.scalar(select(func.count(Announcement.id)).where(
        Announcement.company_id.in_(pids), Announcement.published_at >= since))
    if not in_window:
        # Weekend / holiday / quiet day: show the latest day that had filings rather than nothing.
        latest = db.scalar(select(func.max(Announcement.published_at)).where(
            Announcement.company_id.in_(pids)))
        if latest is not None:
            latest = _aware(latest)
            since = latest.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=6)
            note = (f"Nothing filed in the last {hours}h. "
                    f"Showing the latest filing day ({latest.astimezone().strftime('%a %d %b')}).")

    anns = db.scalars(
        select(Announcement).join(Company)
        .where(Announcement.company_id.in_(pids), Announcement.published_at >= since)
    ).all()
    material = sorted(
        (a for a in anns if a.priority in (Priority.high, Priority.medium)),
        key=lambda a: (_PRIO_RANK[a.priority], -(a.materiality_score or 0), -_aware(a.published_at).timestamp()),
    )
    routine_by_cat: dict = defaultdict(list)
    for a in anns:
        if a.priority not in (Priority.high, Priority.medium):
            routine_by_cat[a.category].append(a)
    routine = sorted(
        (RoutineGroup(category=c, count=len(v),
                      items=[_item(a) for a in sorted(v, key=lambda a: a.published_at, reverse=True)])
         for c, v in routine_by_cat.items()),
        key=lambda g: -g.count,
    )

    sig_rows = db.scalars(
        select(Alert).where(Alert.user_id == user.id, Alert.announcement_id.is_(None),
                            Alert.created_at >= since - timedelta(hours=18))
        .order_by(Alert.created_at.desc())
    ).all()
    cos = {c.id: c for c in db.scalars(select(Company).where(
        Company.id.in_({s.company_id for s in sig_rows} or {-1})))}
    signals = sorted(
        (SignalItem(id=s.id, symbol=cos[s.company_id].nse_symbol, company_name=cos[s.company_id].name, kind=(s.payload or {}).get("kind", ""),
                    priority=s.priority, trade_date=s.trade_date, title=s.title, body=s.body,
                    payload=s.payload) for s in sig_rows),
        key=lambda s: (_PRIO_RANK[s.priority], -(s.trade_date.toordinal() if s.trade_date else 0)),
    )

    return Feed(
        since=since, until=now, requested_hours=hours, note=note,
        counts={"total": len(anns), "material": len(material),
                "routine": len(anns) - len(material), "signals": len(signals)},
        signals=signals, material=[attach_network(db, user, a, _item(a)) for a in material], routine=routine,
    )
