from collections.abc import Sequence

from sqlalchemy.orm import Session


def upsert_rows(
    db: Session, model, rows: Sequence[dict], conflict_cols: list[str], update_cols: list[str]
) -> None:
    """INSERT ... ON CONFLICT DO UPDATE that works on both SQLite and Postgres."""
    if not rows:
        return
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    for i in range(0, len(rows), 500):
        stmt = insert(model).values(list(rows[i : i + 500]))
        if update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_cols,
                set_={c: getattr(stmt.excluded, c) for c in update_cols},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
        db.execute(stmt)
