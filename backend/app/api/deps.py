from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

DEMO_USER_EMAIL = "investor@finn.demo"


def current_user(db: Session = Depends(get_db)) -> User:
    """Prototype: single demo investor. In production this resolves the user from a
    verified session/JWT, and every private query below filters by user.id."""
    user = db.query(User).filter_by(email=DEMO_USER_EMAIL).one_or_none()
    if user is None:
        raise HTTPException(503, "Demo user not seeded. Run: python -m scripts.init_db")
    return user
