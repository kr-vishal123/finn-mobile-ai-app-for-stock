"""Primary-source fundamentals for Pull: financials, documents, chunks, guidance.

Everything in Pull must trace back to a row here (and from there to a document page),
so the UI can cite its sources and we never rely on the model's outside knowledge.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin
from app.models.enums import DocType, GuidanceStatus, PeriodType
from app.models.market import Company


class FinancialPeriod(Base, TimestampMixin):
    """Headline numbers for one quarter or fiscal year. Values in ₹ crore."""

    __tablename__ = "financial_periods"
    __table_args__ = (
        UniqueConstraint("company_id", "period_type", "period_end", "consolidated"),
        Index("ix_fin_company_period", "company_id", "period_type", "period_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    period_type: Mapped[PeriodType] = mapped_column(SAEnum(PeriodType, native_enum=False))
    period_end: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(16))  # "Q2FY27", "FY26"
    consolidated: Mapped[bool] = mapped_column(default=True)

    revenue: Mapped[float | None] = mapped_column(Float)
    ebitda: Mapped[float | None] = mapped_column(Float)
    pbt: Mapped[float | None] = mapped_column(Float)
    pat: Mapped[float | None] = mapped_column(Float)
    eps: Mapped[float | None] = mapped_column(Float)
    # Balance sheet / cash flow (annual mostly): debt, equity, cfo, capex, receivables, ...
    extra: Mapped[dict | None] = mapped_column(JSON)

    source: Mapped[str] = mapped_column(String(32))  # "screener" | "filing" | "llm_extract"
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )


class Document(Base, TimestampMixin):
    """An annual report, concall transcript, investor deck or results filing."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("company_id", "url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    doc_type: Mapped[DocType] = mapped_column(SAEnum(DocType, native_enum=False))
    title: Mapped[str | None] = mapped_column(String(512))
    period_label: Mapped[str | None] = mapped_column(String(16))  # "Q1FY27", "FY26"
    doc_date: Mapped[date | None] = mapped_column(Date)
    url: Mapped[str] = mapped_column(String(1024))
    local_path: Mapped[str | None] = mapped_column(String(1024))
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|fetched|parsed|failed
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company] = relationship()
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    """Retrieval unit. Embeddings are float32 bytes here; pgvector in prod."""

    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(255))  # "MD&A", "Q&A", ...
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_model: Mapped[str | None] = mapped_column(String(128))

    document: Mapped[Document] = relationship(back_populates="chunks")


class GuidanceItem(Base, TimestampMixin):
    """One explicit management promise, and later what was actually delivered.

    Powers "narrative vs numbers": promised (from transcript) vs actual (from FinancialPeriod).
    """

    __tablename__ = "guidance_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    said_in_period: Mapped[str] = mapped_column(String(16))  # "Q1FY26"
    metric: Mapped[str] = mapped_column(String(64))  # revenue_growth, ebitda_margin, capex, ...
    guided_value: Mapped[str] = mapped_column(String(255))  # "15-18%", "~₹500 cr"
    guided_low: Mapped[float | None] = mapped_column(Float)
    guided_high: Mapped[float | None] = mapped_column(Float)
    target_period: Mapped[str | None] = mapped_column(String(16))  # "FY26"
    quote: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)

    actual_value: Mapped[float | None] = mapped_column(Float)
    status: Mapped[GuidanceStatus] = mapped_column(
        SAEnum(GuidanceStatus, native_enum=False), default=GuidanceStatus.pending
    )
    assessment: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict | None] = mapped_column(JSON)  # financial_period ids, chunk ids
