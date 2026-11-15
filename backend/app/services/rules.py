"""Threshold alerts on EOD data. The investor decides what "unusual" means (alert_rules);
this module only applies those thresholds.

The checks are pure functions over plain lists so they are trivially testable.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Alert, AlertRule, Company, PriceBar, User, WatchlistItem
from app.models.enums import AlertRuleType, Priority, WatchlistKind
from app.services.upsert import upsert_rows

DEFAULT_MATERIAL_CATEGORIES = [
    "results", "m_and_a", "management_change", "litigation",
    "fund_raise", "capex", "credit_rating", "pledging",
]


# ---------- pure checks ----------


def volume_ratio(volumes: list[int], lookback: int) -> float | None:
    """Today's volume / mean of the previous `lookback` sessions. volumes are oldest→newest."""
    if len(volumes) < lookback + 1:
        return None
    base = mean(volumes[-lookback - 1 : -1])
    return volumes[-1] / base if base > 0 else None


def pct_change(closes: list[float]) -> float | None:
    if len(closes) < 2 or not closes[-2]:
        return None
    return (closes[-1] / closes[-2] - 1) * 100


@dataclass
class Hit:
    rule: AlertRule
    company: Company
    trade_date: date
    kind: str
    value: float
    threshold: float
    detail: dict


def _fmt_vol(v: float) -> str:
    return f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.0f}K"


# ---------- evaluation over the DB ----------


def ensure_default_rules(db: Session, user: User) -> None:
    if db.scalar(select(AlertRule.id).where(AlertRule.user_id == user.id).limit(1)):
        return
    s = get_settings()
    db.add_all([
        AlertRule(user_id=user.id, rule_type=AlertRuleType.volume_spike,
                  params={"multiple": s.default_volume_spike_multiple,
                          "lookback_days": s.default_volume_lookback_days}),
        AlertRule(user_id=user.id, rule_type=AlertRuleType.price_move,
                  params={"pct": s.default_price_move_pct}),
        AlertRule(user_id=user.id, rule_type=AlertRuleType.announcement_category,
                  params={"categories": DEFAULT_MATERIAL_CATEGORIES}),
    ])
    db.flush()


def _scope(db: Session, user: User, rule: AlertRule) -> list[Company]:
    if rule.company_id:
        return [db.get(Company, rule.company_id)]
    return list(db.scalars(
        select(Company).join(WatchlistItem, WatchlistItem.company_id == Company.id)
        .where(WatchlistItem.user_id == user.id, WatchlistItem.kind == WatchlistKind.portfolio)
    ))


def evaluate_price_rules(db: Session, user: User, sessions: int = 5) -> list[Hit]:
    """Check each of the last `sessions` trading days (so a fresh install has history)."""
    rules = db.scalars(select(AlertRule).where(
        AlertRule.user_id == user.id, AlertRule.enabled.is_(True),
        AlertRule.rule_type.in_([AlertRuleType.volume_spike, AlertRuleType.price_move]),
    )).all()
    hits: list[Hit] = []
    for rule in rules:
        lookback = int(rule.params.get("lookback_days", 20))
        for company in _scope(db, user, rule):
            bars = db.scalars(
                select(PriceBar).where(PriceBar.company_id == company.id)
                .order_by(PriceBar.trade_date.desc()).limit(lookback + sessions + 1)
            ).all()[::-1]
            for end in range(max(len(bars) - sessions, 1), len(bars)):
                window = bars[: end + 1]
                day = window[-1]
                if rule.rule_type == AlertRuleType.volume_spike:
                    thr = float(rule.params.get("multiple", 2.0))
                    r = volume_ratio([b.volume for b in window], lookback)
                    if r is not None and r >= thr:
                        move = pct_change([b.close for b in window])
                        hits.append(Hit(rule, company, day.trade_date, "volume_spike", r, thr, {
                            "volume": day.volume,
                            "avg_volume": round(day.volume / r),
                            "lookback_days": lookback,
                            "close": day.close,
                            "pct_change": round(move, 2) if move is not None else None,
                        }))
                else:
                    thr = float(rule.params.get("pct", 5.0))
                    m = pct_change([b.close for b in window])
                    if m is not None and abs(m) >= thr:
                        hits.append(Hit(rule, company, day.trade_date, "price_move", m, thr, {
                            "close": day.close, "prev_close": window[-2].close,
                            "pct_change": round(m, 2), "volume": day.volume,
                        }))
    return hits


def hit_to_alert_row(user: User, h: Hit) -> dict:
    sym = h.company.nse_symbol
    if h.kind == "volume_spike":
        title = f"{sym} traded {h.value:.1f}× its {h.detail['lookback_days']}-day average volume"
        move = h.detail.get("pct_change")
        body = (f"{_fmt_vol(h.detail['volume'])} shares vs ~{_fmt_vol(h.detail['avg_volume'])} usual"
                + (f"; price {move:+.1f}%" if move is not None else ""))
        severe = h.value >= 2 * h.threshold
    else:
        title = f"{sym} {'jumped' if h.value > 0 else 'fell'} {abs(h.value):.1f}% on the day"
        body = f"Closed ₹{h.detail['close']:,.1f} vs ₹{h.detail['prev_close']:,.1f}"
        severe = abs(h.value) >= 2 * h.threshold
    return {
        "user_id": user.id,
        "rule_id": h.rule.id,
        "company_id": h.company.id,
        "trade_date": h.trade_date,
        "dedupe_key": f"{h.kind}:{sym}:{h.trade_date.isoformat()}",
        "priority": Priority.high if severe else Priority.medium,
        "title": title,
        "body": body,
        "payload": {"kind": h.kind, "value": round(h.value, 3), "threshold": h.threshold, **h.detail},
        # Market data is EOD: stamp the alert at that day's close (15:30 IST) so the feed sorts sanely.
        "created_at": datetime.combine(h.trade_date, time(10, 0), tzinfo=timezone.utc),
    }


def run_announcement_alerts(db: Session, user: User, days: int = 14, min_materiality: int = 3) -> int:
    """Material filings in categories the investor cares about → alerts (deduped per filing)."""
    from datetime import timedelta

    from app.db import utcnow
    from app.models import Announcement

    ensure_default_rules(db, user)
    rules = db.scalars(select(AlertRule).where(
        AlertRule.user_id == user.id, AlertRule.enabled.is_(True),
        AlertRule.rule_type == AlertRuleType.announcement_category)).all()
    rows = []
    for rule in rules:
        cats = set(rule.params.get("categories", []))
        min_m = rule.params.get("min_materiality", min_materiality)
        scope_ids = [c.id for c in _scope(db, user, rule)]
        anns = db.scalars(select(Announcement).where(
            Announcement.company_id.in_(scope_ids),
            Announcement.published_at >= utcnow() - timedelta(days=days),
            Announcement.materiality_score >= min_m,
        )).all()
        for a in anns:
            if a.category is None or a.category.value not in cats:
                continue
            label = a.category.value.replace("_", " ").replace("m and a", "M&A")
            rows.append({
                "user_id": user.id, "rule_id": rule.id, "company_id": a.company_id,
                "announcement_id": a.id, "trade_date": None,
                "dedupe_key": f"ann:{a.id}",
                "priority": a.priority or Priority.medium,
                "title": f"{a.company.nse_symbol} · {label}",
                "body": a.one_liner or a.headline,
                "payload": {"kind": "announcement", "category": a.category.value,
                            "materiality": a.materiality_score},
                "created_at": a.published_at,
            })
    upsert_rows(db, Alert, rows, ["user_id", "dedupe_key"],
                ["title", "body", "payload", "priority", "created_at"])
    db.commit()
    return len(rows)


def run_price_alerts(db: Session, user: User, sessions: int = 5) -> int:
    ensure_default_rules(db, user)
    rows = [hit_to_alert_row(user, h) for h in evaluate_price_rules(db, user, sessions)]
    # Re-runs refresh text/values but keep seen/dismissed state.
    upsert_rows(db, Alert, rows, ["user_id", "dedupe_key"],
                ["title", "body", "payload", "priority", "created_at"])
    db.commit()
    return len(rows)
