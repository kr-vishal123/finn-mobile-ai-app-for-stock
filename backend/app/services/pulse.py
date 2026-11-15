"""'Also worth knowing' for the Today screen: useful even on a day with no filings.

  movers    — last session's biggest moves across the portfolio (and the 5-session move)
  promises  — holdings currently behind their own explicit guidance
  reconnect — the one contact most worth a call this week
All from data FINN already has; no model calls.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, GuidanceItem, PriceBar, User, WatchlistItem
from app.models.enums import GuidanceStatus, WatchlistKind
from app.services.network import keep_warm


def build_pulse(db: Session, user: User) -> dict:
    holdings = list(db.scalars(
        select(Company).join(WatchlistItem, WatchlistItem.company_id == Company.id)
        .where(WatchlistItem.user_id == user.id, WatchlistItem.kind == WatchlistKind.portfolio)))

    movers, as_of = [], None
    for c in holdings:
        bars = list(db.scalars(select(PriceBar).where(PriceBar.company_id == c.id)
                               .order_by(PriceBar.trade_date.desc()).limit(6)))
        if len(bars) < 2:
            continue
        day = (bars[0].close / bars[1].close - 1) * 100
        week = (bars[0].close / bars[-1].close - 1) * 100 if len(bars) == 6 else None
        as_of = max(as_of or bars[0].trade_date, bars[0].trade_date)
        movers.append({"symbol": c.nse_symbol, "close": round(bars[0].close, 1), "day": round(day, 2),
                       "week": round(week, 2) if week is not None else None,
                       "date": bars[0].trade_date.isoformat()})
    movers.sort(key=lambda m: -abs(m["day"]))

    behind = []
    for c in holdings:
        items = list(db.scalars(select(GuidanceItem).where(
            GuidanceItem.company_id == c.id, GuidanceItem.status == GuidanceStatus.missed)))
        if items:
            g = max(items, key=lambda g: g.said_in_period)
            metric = {"revenue_growth": "revenue growth", "ebitda_margin": "EBITDA margin"}.get(g.metric, g.metric)
            behind.append({"symbol": c.nse_symbol, "count": len(items),
                           "line": f"Guided {metric} {g.guided_value} for {g.target_period}; "
                                   f"delivering {g.actual_value:.1f}%" if g.actual_value is not None else g.guided_value})

    warm = keep_warm(db, user)[:2]
    return {"as_of": as_of.isoformat() if as_of else None, "movers": movers[:5],
            "behind": behind[:4], "reconnect": warm}
