from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from core.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeadSegment(str, Enum):
    SKLEP_PLASTYCZNY = "sklep_plastyczny"
    PAINT_AND_SIP = "paint_and_sip"
    WARSZTATY_DZIECI = "warsztaty_dzieci"
    ANIMATORZY_EVENTY = "animatorzy_eventy"
    SZKOLA_ARTYSTYCZNA = "szkola_artystyczna"
    MARKA_WLASNA = "marka_wlasna"
    INNE = "inne"


class LeadStatus(str, Enum):
    NEW = "new"
    RESEARCHED = "researched"
    DRAFTED = "drafted"
    APPROVED = "approved"
    SENT = "sent"
    REPLIED = "replied"
    BOUNCED = "bounced"
    BLACKLISTED = "blacklisted"


class DraftStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    segment: Mapped[str] = mapped_column(String(50), default=LeadSegment.INNE.value)
    company_name: Mapped[str] = mapped_column(String(255))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(500))
    instagram: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="PL")
    source: Mapped[str | None] = mapped_column(String(50))
    score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(50), default=LeadStatus.NEW.value, index=True)
    research_data: Mapped[dict | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    drafts: Mapped[list["EmailDraft"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"))
    template_variant: Mapped[str | None] = mapped_column(String(50))
    subject: Mapped[str | None] = mapped_column(String(500))
    snippet1: Mapped[str | None] = mapped_column(Text)
    snippet2: Mapped[str | None] = mapped_column(Text)
    snippet3: Mapped[str | None] = mapped_column(Text)
    snippet4: Mapped[str | None] = mapped_column(Text)
    snippet5: Mapped[str | None] = mapped_column(Text)
    full_preview: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default=DraftStatus.DRAFT.value, index=True)
    generated_by_model: Mapped[str | None] = mapped_column(String(100))
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    woodpecker_prospect_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)

    lead: Mapped["Lead"] = relationship(back_populates="drafts")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(100), index=True)
    level: Mapped[str] = mapped_column(String(20), default="INFO", index=True)
    source: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


_engine = create_engine(settings.db_url, echo=False, future=True)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    settings.db_file.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_engine)


def get_session():
    return SessionLocal()
