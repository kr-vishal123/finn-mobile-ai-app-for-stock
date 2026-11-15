"""The investor's network: a private graph of people, where they worked/studied, and links.

Privacy model: every person and every edge is owned by exactly one user (`owner_id`).
The same real person can exist under two owners as two separate rows; nothing about one
investor's network ever leaks into another's. Company rows are the only shared join point.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin, utcnow
from app.models.enums import ProfileSource, RelationshipType
from app.models.market import Company


class Person(Base, TimestampMixin):
    """Anyone FINN knows about for this user: a contact, or someone named in a filing."""

    __tablename__ = "people"
    __table_args__ = (Index("ix_people_owner_name", "owner_id", "name_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    # lowercase, no honorifics ("Mr.", "Dr.", "Shri"), single spaces. Used for filing → person matching.
    name_normalized: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list | None] = mapped_column(JSON)
    headline: Mapped[str | None] = mapped_column(String(512))
    location: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    profile_url: Mapped[str | None] = mapped_column(String(1024))
    source: Mapped[ProfileSource] = mapped_column(
        SAEnum(ProfileSource, native_enum=False), default=ProfileSource.synthetic
    )
    # Retention: profiles of non-contacts (e.g. someone named in a filing) expire.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    experiences: Mapped[list["Experience"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    educations: Mapped[list["Education"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    expertise: Mapped[list["Expertise"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    contact: Mapped["Contact | None"] = relationship(back_populates="person", uselist=False)


class Experience(Base):
    __tablename__ = "experiences"
    __table_args__ = (Index("ix_exp_company", "company_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    # Linked when the employer is a listed company we know; org_name always kept verbatim.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    org_name: Mapped[str] = mapped_column(String(255))
    org_name_normalized: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    function: Mapped[str | None] = mapped_column(String(64))  # finance, ops, sales, board, ...
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)  # NULL = current
    source_announcement_id: Mapped[int | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL")
    )

    person: Mapped[Person] = relationship(back_populates="experiences")
    company: Mapped[Company | None] = relationship()


class Education(Base):
    __tablename__ = "educations"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    institution: Mapped[str] = mapped_column(String(255))
    institution_normalized: Mapped[str] = mapped_column(String(255), index=True)
    degree: Mapped[str | None] = mapped_column(String(128))
    field: Mapped[str | None] = mapped_column(String(128))
    start_year: Mapped[int | None] = mapped_column(Integer)
    end_year: Mapped[int | None] = mapped_column(Integer)

    person: Mapped[Person] = relationship(back_populates="educations")


class Expertise(Base):
    """Theme tags for the expertise map ("specialty chemicals", "rural lending")."""

    __tablename__ = "expertise"
    __table_args__ = (UniqueConstraint("person_id", "theme"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    theme: Mapped[str] = mapped_column(String(128), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(16), default="inferred")  # inferred | user

    person: Mapped[Person] = relationship(back_populates="expertise")


class Contact(Base, TimestampMixin):
    """A first-degree relationship: the investor knows this person directly."""

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("owner_id", "person_id"),
        CheckConstraint("strength BETWEEN 1 AND 5", name="ck_contact_strength"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"))
    relationship_type: Mapped[RelationshipType] = mapped_column(
        SAEnum(RelationshipType, native_enum=False)
    )
    strength: Mapped[int] = mapped_column(Integer, default=3)  # 1 = acquaintance, 5 = close
    how_met: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Consent: has this contact agreed to be stored / enriched? (real deployment)
    consent_status: Mapped[str] = mapped_column(String(16), default="implied")

    person: Mapped[Person] = relationship(back_populates="contact")


class PersonLink(Base):
    """A known edge between two people (for second-degree reach).

    Shared employer/school overlaps are computed from Experience/Education at query time;
    this table holds edges the investor knows about or that were stated explicitly.
    Stored once with person_a_id < person_b_id.
    """

    __tablename__ = "person_links"
    __table_args__ = (
        UniqueConstraint("owner_id", "person_a_id", "person_b_id", "link_type"),
        CheckConstraint("person_a_id < person_b_id", name="ck_link_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_a_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    person_b_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    link_type: Mapped[str] = mapped_column(String(32))  # colleague, classmate, board, family, ...
    strength: Mapped[float] = mapped_column(Float, default=0.5)  # 0..1
    evidence: Mapped[str | None] = mapped_column(Text)


class Interaction(Base):
    """Log of meetings/calls. Drives "keep the network warm" and "met in the last 2-3 years"."""

    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    channel: Mapped[str | None] = mapped_column(String(32))  # meeting, call, conference, email
    note: Mapped[str | None] = mapped_column(Text)
