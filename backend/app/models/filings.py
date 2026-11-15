"""Corporate announcements from NSE/BSE, with FINN's classification and enrichment."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin
from app.models.enums import AnnouncementCategory, Exchange, Priority
from app.models.market import Company


class Announcement(Base, TimestampMixin):
    __tablename__ = "announcements"
    __table_args__ = (
        # Dedupe: the same filing must never be ingested twice.
        UniqueConstraint("exchange", "exchange_ref"),
        Index("ix_ann_company_time", "company_id", "published_at"),
        Index("ix_ann_time", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    exchange: Mapped[Exchange] = mapped_column(SAEnum(Exchange, native_enum=False))
    exchange_ref: Mapped[str] = mapped_column(String(128))  # exchange's own id / attachment name
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Raw, as filed
    exchange_category: Mapped[str | None] = mapped_column(String(255))  # exchange's own label
    headline: Mapped[str] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    attachment_url: Mapped[str | None] = mapped_column(String(1024))

    # FINN's classification (cheap model + rules)
    category: Mapped[AnnouncementCategory | None] = mapped_column(
        SAEnum(AnnouncementCategory, native_enum=False), index=True
    )
    category_confidence: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[Priority | None] = mapped_column(SAEnum(Priority, native_enum=False))
    materiality_score: Mapped[float | None] = mapped_column(Float)  # 1..5, used for sorting
    one_liner: Mapped[str | None] = mapped_column(String(512))
    # Type-specific structured output, e.g.
    #   management_change: {"person_name", "role", "direction": "joining"|"leaving", "person_id"}
    #   results:           {"financial_period_id": ...}
    #   m_and_a / capex:   {"counterparty", "amount_cr", ...}
    enrichment: Mapped[dict | None] = mapped_column(JSON)
    processed_by_model: Mapped[str | None] = mapped_column(String(128))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company] = relationship()
