from datetime import timedelta

from fastapi.testclient import TestClient  # noqa: E402

from app.api.deps import DEMO_USER_EMAIL  # noqa: E402
from app.db import SessionLocal, init_db, utcnow  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Announcement, Company, User, WatchlistItem  # noqa: E402
from app.models.enums import AnnouncementCategory, Exchange, Priority  # noqa: E402
from app.services.normalize import normalize_org_name, normalize_person_name  # noqa: E402


def _seed():
    init_db()
    with SessionLocal() as db:
        u = User(email=DEMO_USER_EMAIL, name="Demo")
        c = Company(nse_symbol="TCS", name="Tata Consultancy Services Ltd",
                    name_normalized=normalize_org_name("Tata Consultancy Services Ltd"))
        db.add_all([u, c]); db.flush()
        db.add(WatchlistItem(user_id=u.id, company_id=c.id))
        now = utcnow()
        for i, (prio, cat) in enumerate([(Priority.low, AnnouncementCategory.unclassified),
                                         (Priority.high, AnnouncementCategory.results),
                                         (Priority.medium, AnnouncementCategory.dividend)]):
            db.add(Announcement(company_id=c.id, exchange=Exchange.NSE, exchange_ref=f"r{i}",
                                published_at=now - timedelta(hours=i + 1), headline=cat.value,
                                category=cat, priority=prio))
        db.add(Announcement(company_id=c.id, exchange=Exchange.NSE, exchange_ref="old",
                            published_at=now - timedelta(days=5), headline="old",
                            priority=Priority.high))
        db.commit()


_seed()
client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_feed_window_priority_and_routine_collapse():
    f = client.get("/api/feed?hours=24").json()
    assert [x["priority"] for x in f["material"]] == ["high", "medium"]
    assert f["routine"][0]["category"] == "unclassified" and f["routine"][0]["count"] == 1
    assert f["note"] is None
    assert client.get("/api/feed?hours=200").json()["counts"]["total"] == 4


def test_company_and_watchlist():
    assert client.get("/api/companies/tcs").json()["nse_symbol"] == "TCS"
    assert client.get("/api/companies/NOPE").status_code == 404
    assert client.get("/api/watchlist").json()[0]["company"]["nse_symbol"] == "TCS"


def test_alert_rule_bounds():
    with SessionLocal() as db:
        from app.services.rules import ensure_default_rules
        ensure_default_rules(db, db.query(User).first()); db.commit()
    rules = {r["rule_type"]: r for r in client.get("/api/alert-rules").json()}
    rid = rules["volume_spike"]["id"]
    assert client.put(f"/api/alert-rules/{rid}", json={"params": {"multiple": 0.5}}).status_code == 422
    r = client.put(f"/api/alert-rules/{rid}", json={"params": {"multiple": 3}}).json()
    assert r["params"]["multiple"] == 3.0


def test_normalize():
    assert normalize_person_name("Mr. Rajesh  K. Gopinathan") == "rajesh k gopinathan"
    assert normalize_org_name("Larsen & Toubro Limited") == "larsen and toubro"
