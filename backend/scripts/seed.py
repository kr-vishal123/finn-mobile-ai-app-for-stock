"""Seed the demo: investor, universe, watchlists, default alert rules, prices, price alerts.

    cd backend && python -m scripts.seed            # everything
    python -m scripts.seed --skip-prices --offline   # no network at all
"""

import argparse

from sqlalchemy import select

from app.api.deps import DEMO_USER_EMAIL
from app.db import SessionLocal, init_db
from app.models import Company, User, WatchlistItem
from app.models.enums import WatchlistKind
from app.seed.universe import PORTFOLIO, RESEARCH
from app.services.companies import upsert_company
from app.services.prices import ingest_prices
from app.models import GuidanceItem
from app.services.announcements import ingest_announcements
from app.services.filing_text import enrich_filings
from app.services.fundamentals import ensure_fundamentals
from app.services.guidance import build_guidance
from app.services.results import enrich_results
from scripts.seed_network import main as seed_network
from app.services.rules import ensure_default_rules, run_announcement_alerts, run_price_alerts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-prices", action="store_true")
    ap.add_argument("--offline", action="store_true", help="no NSE calls; use snapshots")
    args = ap.parse_args()

    init_db()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == DEMO_USER_EMAIL))
        if user is None:
            user = User(email=DEMO_USER_EMAIL, name="Demo Investor")
            db.add(user)
            db.flush()

        n = len(PORTFOLIO)
        for kind, universe in ((WatchlistKind.portfolio, PORTFOLIO), (WatchlistKind.research, RESEARCH)):
            for sym, name, sector, industry in universe:
                c = upsert_company(db, sym, name, sector, industry)
                exists = db.scalar(select(WatchlistItem).where(
                    WatchlistItem.user_id == user.id, WatchlistItem.company_id == c.id,
                    WatchlistItem.kind == kind))
                if not exists:
                    db.add(WatchlistItem(
                        user_id=user.id, company_id=c.id, kind=kind,
                        weight_pct=round(100 / n, 2) if kind == WatchlistKind.portfolio else None))
        ensure_default_rules(db, user)
        db.commit()
        print(f"Universe: {len(PORTFOLIO)} portfolio + {len(RESEARCH)} research")

        # Only names the investor follows; network peers are reference rows, fetched lazily if opened.
        companies = list(db.scalars(select(Company).join(WatchlistItem, WatchlistItem.company_id == Company.id)
                                    .where(WatchlistItem.user_id == user.id).distinct()))
        if not args.skip_prices:
            stats = ingest_prices(db, companies)
            print(f"Prices: {stats['rows']} bars for {stats['tickers']} tickers; missing={stats['missing']}")
            print(f"Price alerts (last 5 sessions): {run_price_alerts(db, user)}")
        # --offline uses the committed NSE snapshots (backend/snapshots/nse) — no network needed.
        print("Announcements:", ingest_announcements(db, companies, live=not args.offline))
        print("Filing PDFs:", enrich_filings(db))

        for c in companies:
            ensure_fundamentals(db, c, live=not args.offline)
        print("Results cards:", enrich_results(db))
        for c in companies:
            build_guidance(db, c)
        print("Guidance items:", db.query(GuidanceItem).count())

        seed_network()
        print(f"Announcement alerts (14d): {run_announcement_alerts(db, user)}")


if __name__ == "__main__":
    main()
