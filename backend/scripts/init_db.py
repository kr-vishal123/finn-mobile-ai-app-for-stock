"""Create all tables and the demo investor. Safe to re-run.

    cd backend && python -m scripts.init_db
"""

from sqlalchemy import inspect

from app.api.deps import DEMO_USER_EMAIL
from app.db import SessionLocal, engine, init_db
from app.models import User


def main() -> None:
    init_db()
    with SessionLocal() as db:
        if not db.query(User).filter_by(email=DEMO_USER_EMAIL).first():
            db.add(User(email=DEMO_USER_EMAIL, name="Demo Investor"))
            db.commit()
    tables = sorted(inspect(engine).get_table_names())
    print(f"DB ready at {engine.url} — {len(tables)} tables:")
    for t in tables:
        print(f"  - {t}")


if __name__ == "__main__":
    main()
