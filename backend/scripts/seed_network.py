"""Load the SYNTHETIC demo network for the demo investor (idempotent: replaces it).

    python -m scripts.seed_network
"""

from datetime import date, timedelta

from sqlalchemy import delete, select

from app.api.deps import DEMO_USER_EMAIL
from app.db import SessionLocal, init_db, utcnow
from app.models import Contact, Education, Experience, Expertise, Interaction, Person, PersonLink, User
from app.models.enums import ProfileSource, RelationshipType
from app.seed.network import LINKS, PEERS, PEOPLE
from app.services.companies import upsert_company
from app.services.network import match_company
from app.services.normalize import normalize_org_name, normalize_person_name


def main() -> None:
    init_db()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == DEMO_USER_EMAIL))
        for sym, name, sector, industry in PEERS:
            upsert_company(db, sym, name, sector, industry)
        db.flush()
        # Replace this owner's network wholesale (cascades to experiences, contacts, ...).
        for model in (PersonLink, Interaction, Contact):
            db.execute(delete(model).where(model.owner_id == user.id))
        for p in db.scalars(select(Person).where(Person.owner_id == user.id)):
            db.delete(p)
        db.flush()

        ids: dict[str, int] = {}
        now = utcnow()
        for (name, headline, loc, rel, strength, months, how, exps, edus, tags) in PEOPLE:
            p = Person(owner_id=user.id, full_name=name, name_normalized=normalize_person_name(name),
                       headline=headline, location=loc, source=ProfileSource.synthetic)
            db.add(p)
            db.flush()
            ids[name] = p.id
            for org, title, fn, s, e in exps:
                co = match_company(db, org)
                db.add(Experience(person_id=p.id, company_id=co.id if co else None, org_name=org,
                                  org_name_normalized=normalize_org_name(org), title=title, function=fn,
                                  start_date=date(s, 6, 1), end_date=date(e, 5, 31) if e else None))
            for inst, deg, s, e in edus:
                db.add(Education(person_id=p.id, institution=inst, institution_normalized=normalize_org_name(inst),
                                 degree=deg, start_year=s, end_year=e))
            for t in tags:
                db.add(Expertise(person_id=p.id, theme=t, source="user"))
            if rel:
                last = now - timedelta(days=int(months * 30.4))
                db.add(Contact(owner_id=user.id, person_id=p.id, relationship_type=RelationshipType(rel),
                               strength=strength, how_met=how, last_interaction_at=last))
                db.add(Interaction(owner_id=user.id, person_id=p.id, occurred_at=last, channel="meeting", note=how))
        for a, b, kind, s, ev in LINKS:
            x, y = sorted((ids[a], ids[b]))
            db.add(PersonLink(owner_id=user.id, person_a_id=x, person_b_id=y, link_type=kind, strength=s, evidence=ev))
        db.commit()
        linked = db.query(Experience).filter(Experience.company_id.isnot(None)).count()
        print(f"Network: {len(PEOPLE)} synthetic people, {len(LINKS)} links, {linked} employer links to listed companies")


if __name__ == "__main__":
    main()
