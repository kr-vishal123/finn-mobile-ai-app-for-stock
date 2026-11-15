"""Push: user-defined alert rules and the alerts they fire."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin, utcnow
from app.models.enums import AlertRuleType, Priority


class AlertRule(Base, TimestampMixin):
    """What the investor considers "unusual". company_id NULL = whole portfolio.

    params by rule_type:
      announcement_category: {"categories": ["results", "m_and_a", ...]}
      volume_spike:          {"multiple": 2.0, "lookback_days": 20}
      price_move:            {"pct": 5.0}
    """

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    rule_type: Mapped[AlertRuleType] = mapped_column(SAEnum(AlertRuleType, native_enum=False))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        # One alert per (user, rule, subject) — re-running the evaluator is idempotent.
        UniqueConstraint("user_id", "dedupe_key"),
        Index("ix_alert_user_time", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    announcement_id: Mapped[int | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE")
    )
    trade_date: Mapped[date | None] = mapped_column(Date)  # for price/volume alerts
    dedupe_key: Mapped[str] = mapped_column(String(255))
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority, native_enum=False))
    title: Mapped[str] = mapped_column(String(512))
    body: Mapped[str | None] = mapped_column(Text)
    # Rendering payload: metrics, results table, bio, suggested network contacts + reasons
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rule: Mapped[AlertRule | None] = relationship()
