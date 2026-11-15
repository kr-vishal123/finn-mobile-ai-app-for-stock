"""Fetch screener fundamentals for every company, then attach numbers to results filings.

    python -m scripts.ingest_fundamentals            # live, polite (1 req/s), snapshot fallback
    python -m scripts.ingest_fundamentals --offline  # snapshots only
"""

import argparse
import time

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Company
from app.services.fundamentals import ensure_fundamentals
from app.services.results import enrich_results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    init_db()
    with SessionLocal() as db:
        for c in db.scalars(select(Company).order_by(Company.nse_symbol)):
            how = ensure_fundamentals(db, c, max_age_hours=0 if args.force else 24, live=not args.offline)
            print(f"{c.nse_symbol:12} {how}")
            if how == "live":
                time.sleep(1.0)
        print("results cards enriched:", enrich_results(db))


if __name__ == "__main__":
    main()
