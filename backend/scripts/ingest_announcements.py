"""Fetch NSE announcements for every company in the DB, then classify.

    python -m scripts.ingest_announcements              # live NSE, falls back to snapshots
    python -m scripts.ingest_announcements --offline    # snapshots only
    python -m scripts.ingest_announcements --reclassify # re-run classification on everything
"""

import argparse

from sqlalchemy import select, update

from app.db import SessionLocal, init_db
from app.models import Announcement, Company
from app.services.announcements import classify_pending, ingest_announcements


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--reclassify", action="store_true")
    args = ap.parse_args()
    init_db()
    with SessionLocal() as db:
        if args.reclassify:
            db.execute(update(Announcement).values(processed_at=None))
            db.commit()
            print(classify_pending(db))
            return
        companies = list(db.scalars(select(Company).where(Company.nse_symbol.is_not(None))))
        print(ingest_announcements(db, companies, days=args.days, live=not args.offline))


if __name__ == "__main__":
    main()
