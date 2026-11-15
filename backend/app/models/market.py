"""Investors, companies, watchlists and end-of-day prices."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
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

from app.db import Base, TimestampMixin, utcnow
from app.models.enums import WatchlistKind


class User(Base, TimestampMixin):
    """The investor. Every private row (network, watchlist, alerts) is scoped to a user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")


class Company(Base, TimestampMixin):
    """Public reference data, shared across users."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    nse_symbol: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    bse_code: Mapped[str | None] = mapped_column(String(16), unique=True, index=True)
    isin: Mapped[str | None] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    # Lower-cased name without "Ltd/Limited/Pvt" etc. Used to match employer strings
    # in profiles and filings back to a company row.
    name_normalized: Mapped[str] = mapped_column(String(255), index=True)
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    market_cap_cr: Mapped[float | None] = mapped_column(Float)
    screener_slug: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)

    prices: Mapped[list["PriceBar"]] = relationship(back_populates="company")

    @property
    def yf_ticker(self) -> str | None:
        if self.nse_symbol:
            return f"{self.nse_symbol}.NS"
        if self.bse_code:
            return f"{self.bse_code}.BO"
        return None


class WatchlistItem(Base):
    """A company in a user's portfolio or research list."""

    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("user_id", "company_id", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    kind: Mapped[WatchlistKind] = mapped_column(
        SAEnum(WatchlistKind, native_enum=False), default=WatchlistKind.portfolio
    )
    weight_pct: Mapped[float | None] = mapped_column(Float)
    thesis: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Company] = relationship()


class PriceBar(Base):
    """End-of-day OHLCV, one row per company per trading day."""

    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("company_id", "trade_date"),
        Index("ix_price_company_date", "company_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    trade_date: Mapped[date] = mapped_column(Date)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger)

    company: Mapped[Company] = relationship(back_populates="prices")
