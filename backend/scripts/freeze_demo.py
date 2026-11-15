"""Write a compact copy of the dev DB to snapshots/demo.db (committed).

A fresh deploy boots from it, so the demo never depends on Yahoo/NSE being reachable
from the cloud host at review time.

    python -m scripts.freeze_demo
"""

import sqlite3

from app.config import BACKEND_DIR, get_settings

DEMO_DB = BACKEND_DIR / "snapshots" / "demo.db"


def main() -> None:
    src = get_settings().resolved_database_url.removeprefix("sqlite:///")
    DEMO_DB.unlink(missing_ok=True)
    with sqlite3.connect(src) as con:
        con.execute("VACUUM INTO ?", (str(DEMO_DB),))
    print(f"Froze {src} -> {DEMO_DB} ({DEMO_DB.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
