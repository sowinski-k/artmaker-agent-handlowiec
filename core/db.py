from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
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


# ─── Enums ──────────────────────────────────────────────────────────────

class LeadSegment(str, Enum):
    SKLEP_PLASTYCZNY = "sklep_plastyczny"
    SKLEP_PAPIERNICZY = "sklep_papierniczy"
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


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    DISCOVERY_PIPELINE = "discovery_pipeline"  # discovery + research + (auto-draft)
    RESEARCH_LEAD = "research_lead"            # pojedynczy lead z URL
    BULK_RESEARCH_LEADS = "bulk_research_leads"  # lista URLi do researchu (praca ręczna)
    GENERATE_DRAFT = "generate_draft"          # draft dla lead_id
    BULK_GENERATE_DRAFTS = "bulk_generate_drafts"
    SEND_DRAFT = "send_draft"                  # push do Woodpecker
    POLL_WOODPECKER = "poll_woodpecker"        # update statusów replied/bounced


class WorkspaceRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Base(DeclarativeBase):
    pass


# ─── Multi-tenant: User + Workspace ─────────────────────────────────────

class User(Base):
    """Klient SaaS. Każdy może należeć do wielu Workspace'ów (przez WorkspaceMember)."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)  # super-admin (Twoje konto)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class Workspace(Base):
    """Konto klienta. Każdy klient ma własny workspace z izolowanymi danymi.
    Lead, EmailDraft, Event, Job są kontekstualizowane przez workspace_id."""
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan: Mapped[str] = mapped_column(String(50), default="free")
    monthly_credits: Mapped[int] = mapped_column(Integer, default=100)
    used_credits: Mapped[int] = mapped_column(Integer, default=0)
    # Per-workspace API keys (szyfrowane / encoded base64; w produkcji dorzucić Fernet)
    api_keys: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class WorkspaceMember(Base):
    """User <-> Workspace many-to-many z rolą."""
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=WorkspaceRole.MEMBER.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ─── Lead / EmailDraft / Event teraz z workspace_id ─────────────────────

class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    # workspace_id nullable na potrzeby migracji starych danych - kod
    # filter'uje by workspace, ale fallback do "default workspace" w razie
    # potrzeby. Po commit 4 wszystkie nowe leady mają workspace_id.
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True,
    )
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
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True,
    )
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
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True,
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(100), index=True)
    level: Mapped[str] = mapped_column(String(20), default="INFO", index=True)
    source: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ─── Job queue (worker process polluje) ─────────────────────────────────

class Job(Base):
    """Background job - worker polluje co N sekund pending jobs i wykonuje.
    Pozwala na 'fire and forget' z UI - user może wylogować się, job leci dalej.
    """
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=JobStatus.PENDING.value, index=True,
    )
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)

    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


# ─── Engine + session ────────────────────────────────────────────────────

_engine = create_engine(settings.db_url, echo=False, future=True)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Tworzy tabele i upewnia się że istnieje default workspace + admin user.

    Default workspace dostaje stare leady (z workspace_id=NULL przed migracją)
    przy pierwszym uruchomieniu po deploy. Admin user (z env ADMIN_EMAIL) jest
    automatycznie tworzony - to Twoje konto.

    Idempotentna migracja kolumn workspace_id: jeśli stara DB istnieje bez
    workspace_id, doklejamy kolumnę (ALTER TABLE) zanim odpalimy resztę.
    """
    if str(settings.db_url).startswith("sqlite"):
        # Local dev: stwórz folder dla pliku DB
        settings.db_file.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_engine)
    _migrate_workspace_columns()
    _ensure_default_workspace()


def _migrate_workspace_columns() -> None:
    """Dokleja workspace_id do leads/email_drafts/events jeśli stara DB.

    Bezpieczne dla obu Postgres i SQLite. KAŻDY ALTER w osobnej transakcji -
    bo Postgres "aborts" transakcję na pierwszym błędzie (column already exists)
    i wszystkie kolejne ALTERy w tej samej transakcji by się sypały.
    Idempotent: kolumna już istnieje -> exception zignorowany.
    """
    import logging
    log = logging.getLogger("ecombinat.migrate")
    from sqlalchemy import text
    is_pg = not str(settings.db_url).startswith("sqlite")
    migrations = [
        ("leads", "workspace_id", "INTEGER"),
        ("leads", "city", "VARCHAR(100)"),
        ("leads", "instagram", "VARCHAR(255)"),
        ("leads", "source", "VARCHAR(50)"),
        ("leads", "research_data", "JSON" if is_pg else "TEXT"),
        ("leads", "notes", "TEXT"),
        ("email_drafts", "workspace_id", "INTEGER"),
        ("email_drafts", "snippet4", "TEXT"),
        ("email_drafts", "snippet5", "TEXT"),
        ("email_drafts", "edited_by_user", "BOOLEAN DEFAULT FALSE" if is_pg else "INTEGER DEFAULT 0"),
        ("events", "workspace_id", "INTEGER"),
        ("events", "user_id", "INTEGER"),
        ("events", "payload", "JSON" if is_pg else "TEXT"),
    ]
    added = 0
    for table, column, coltype in migrations:
        try:
            with _engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
                added += 1
        except Exception as exc:
            # Kolumna już istnieje (najczęściej) lub tabela nie istnieje - OK
            msg = str(exc).lower()
            if "already exists" not in msg and "duplicate column" not in msg:
                log.warning(f"ALTER TABLE {table} ADD COLUMN {column} skipped: {exc}")
    if added:
        log.info(f"Schema migration: added {added} columns")


def _ensure_default_workspace() -> None:
    """Idempotent: tworzy 'default' workspace + admin user jeśli jeszcze nie ma.

    Wszystkie stare dane (Lead, EmailDraft, Event bez workspace_id) są
    przypisane do tego workspace'u.

    Hasło admina: jeśli ADMIN_PASSWORD/APP_PASSWORD jest ustawione w env i
    różni się od bieżącego hasha - UPDATE'ujemy. Pozwala na zmianę hasła
    bez resetowania bazy (poprzednio admin dostawał default "ecombinat-admin"
    przy pierwszym deploy i potem env był ignorowany).
    """
    import logging
    import os
    from sqlalchemy import select, update

    log = logging.getLogger("ecombinat.bootstrap")

    admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    if not admin_email:
        return  # bez ADMIN_EMAIL nie tworzymy nic automatycznie

    admin_pw = (os.getenv("APP_PASSWORD") or os.getenv("ADMIN_PASSWORD") or "").strip()

    with SessionLocal() as session:
        admin = session.execute(select(User).where(User.email == admin_email)).scalar_one_or_none()
        if admin is None:
            # Stwórz admina
            from web.auth import hash_password  # lazy import żeby uniknąć cyklicznych
            pw_to_use = admin_pw or "ecombinat-admin"
            admin = User(
                email=admin_email,
                password_hash=hash_password(pw_to_use),
                name="Admin",
                is_admin=True,
            )
            session.add(admin)
            session.flush()
            log.info(f"Admin user CREATED: {admin_email}")
        elif admin_pw:
            # Admin istnieje. Jeśli env-set password nie pasuje - UPDATE.
            from web.auth import hash_password, verify_password
            if not verify_password(admin_pw, admin.password_hash):
                admin.password_hash = hash_password(admin_pw)
                session.flush()
                log.info(f"Admin password RESET from env for {admin_email}")

        # Default workspace dla admina
        ws = session.execute(
            select(Workspace).where(Workspace.owner_user_id == admin.id, Workspace.slug == "default")
        ).scalar_one_or_none()
        if ws is None:
            ws = Workspace(
                name="Default Workspace",
                slug="default",
                owner_user_id=admin.id,
                plan="enterprise",
                monthly_credits=99999,
            )
            session.add(ws)
            session.flush()

        # Upewnij się że admin jest członkiem swojego workspace'u
        member = session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == admin.id,
            )
        ).scalar_one_or_none()
        if member is None:
            session.add(WorkspaceMember(
                workspace_id=ws.id,
                user_id=admin.id,
                role=WorkspaceRole.OWNER.value,
            ))

        # Migracja starych danych: przypisz wszystkie NULL workspace_id do default
        session.execute(update(Lead).where(Lead.workspace_id.is_(None)).values(workspace_id=ws.id))
        session.execute(update(EmailDraft).where(EmailDraft.workspace_id.is_(None)).values(workspace_id=ws.id))
        session.execute(update(Event).where(Event.workspace_id.is_(None)).values(workspace_id=ws.id))
        session.commit()


def get_session():
    return SessionLocal()
