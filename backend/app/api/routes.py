"""HTTP API. Thin: request parsing + auth scoping here, logic in app/services."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.schemas import (
    AlertOut,
    AlertRuleIn,
    AlertRuleOut,
    CompanyOut,
    Feed,
    FinancialPeriodOut,
    WatchlistItemOut,
)
from app.db import get_db, utcnow
from app.models import (Alert, AlertRule, Company, Expertise, FinancialPeriod, GuidanceItem, Person,
                        User, WatchlistItem)
from app.models.enums import AlertRuleType, PeriodType
from app.services import network
from app.services.ask import answer
from app.services.companies import ensure_company
from app.services.feed import build_feed
from app.services.fundamentals import ensure_fundamentals
from app.services.guidance import build_guidance
from app.services.research import build_research
from app.services.results import enrich_results
from app.services.rules import run_announcement_alerts, run_price_alerts

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------- Companies & portfolio ----------


@router.get("/companies/{symbol}", response_model=CompanyOut)
def get_company(symbol: str, db: Session = Depends(get_db)) -> Company:
    company = db.scalar(select(Company).where(Company.nse_symbol == symbol.upper()))
    if company is None:
        raise HTTPException(404, f"Unknown symbol {symbol}")
    return company


@router.get("/watchlist", response_model=list[WatchlistItemOut])
def watchlist(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(WatchlistItem).where(WatchlistItem.user_id == user.id)).all()


# ---------- Push: digest ----------


@router.get("/feed", response_model=Feed)
def feed(
    hours: int = Query(24, ge=1, le=24 * 90),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return build_feed(db, user, hours)


# ---------- Push: alerts + the investor's thresholds ----------


@router.get("/alerts", response_model=list[AlertOut])
def alerts(
    unseen: bool = False, limit: int = Query(50, le=200),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    q = select(Alert).where(Alert.user_id == user.id, Alert.dismissed_at.is_(None))
    if unseen:
        q = q.where(Alert.seen_at.is_(None))
    return db.scalars(q.order_by(Alert.created_at.desc()).limit(limit)).all()


@router.post("/alerts/{alert_id}/seen", response_model=AlertOut)
def mark_seen(alert_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if a is None or a.user_id != user.id:  # never reveal other users' rows
        raise HTTPException(404)
    a.seen_at = a.seen_at or utcnow()
    db.commit()
    return a


@router.get("/alert-rules", response_model=list[AlertRuleOut])
def alert_rules(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(AlertRule).where(AlertRule.user_id == user.id).order_by(AlertRule.id)).all()


_PARAM_BOUNDS = {
    AlertRuleType.volume_spike: {"multiple": (1.1, 20.0), "lookback_days": (5, 120)},
    AlertRuleType.price_move: {"pct": (0.5, 50.0)},
}


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleOut)
def update_alert_rule(
    rule_id: int, body: AlertRuleIn,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    rule = db.get(AlertRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(404)
    params = dict(rule.params)
    for k, (lo, hi) in _PARAM_BOUNDS.get(rule.rule_type, {}).items():
        if k in body.params:
            v = float(body.params[k])
            if not lo <= v <= hi:
                raise HTTPException(422, f"{k} must be between {lo} and {hi}")
            params[k] = v
    if rule.rule_type == AlertRuleType.announcement_category and "categories" in body.params:
        params["categories"] = [str(c) for c in body.params["categories"]]
    rule.params, rule.enabled = params, body.enabled
    db.commit()
    # Re-evaluate immediately so the investor sees the effect of the new threshold.
    run_price_alerts(db, user)
    run_announcement_alerts(db, user)
    return rule


# ---------- Pull ----------


@router.get("/pull/{symbol}/quarters", response_model=list[FinancialPeriodOut])
def quarters(symbol: str, n: int = Query(8, ge=1, le=40), db: Session = Depends(get_db)):
    company = get_company(symbol, db)
    stmt = (
        select(FinancialPeriod)
        .where(FinancialPeriod.company_id == company.id,
               FinancialPeriod.period_type == PeriodType.quarter)
        .order_by(FinancialPeriod.period_end.desc())
        .limit(n)
    )
    return db.scalars(stmt).all()


@router.get("/research/{symbol}")
def research(symbol: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Any NSE symbol. First request for an unseen ticker fetches fundamentals + transcripts
    (slow, once); later requests are served from the DB."""
    company = ensure_company(db, symbol)
    if company is None:
        raise HTTPException(404, f"{symbol.upper()} isn't a listed NSE symbol we can resolve")
    how = ensure_fundamentals(db, company)
    if how == "unavailable":
        raise HTTPException(503, f"No fundamentals available for {company.nse_symbol} right now")
    if how == "live" or not db.scalar(select(GuidanceItem.id).where(GuidanceItem.company_id == company.id).limit(1)):
        build_guidance(db, company)
        enrich_results(db, company.id)
    return build_research(db, user, company)


# ---------- Network (always scoped to the current user) ----------


@router.get("/network/who/{symbol}")
def network_who(symbol: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    company = get_company(symbol, db)
    return network.who_to_call(db, user, company, limit=5)


@router.get("/network/expertise")
def network_expertise(q: str = Query(..., min_length=2), user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    return network.expertise(db, user, q)


@router.get("/network/keep-warm")
def network_keep_warm(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return network.keep_warm(db, user)


@router.get("/network/people/{person_id}")
def network_person(person_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    card = network.person_card(db, user, person_id)
    if card is None:
        raise HTTPException(404)
    return card


@router.get("/network/themes")
def network_themes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Expertise map: themes across the network, with how many people cover each."""
    rows = db.execute(
        select(Expertise.theme, func.count(Expertise.id)).join(Person, Person.id == Expertise.person_id)
        .where(Person.owner_id == user.id).group_by(Expertise.theme).order_by(func.count(Expertise.id).desc())
    ).all()
    return [{"theme": t, "people": n} for t, n in rows]


@router.post("/ask")
def ask(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = str(body.get("q", ""))[:300]
    return answer(db, user, q)


@router.get("/pulse")
def pulse(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services.pulse import build_pulse
    return build_pulse(db, user)
