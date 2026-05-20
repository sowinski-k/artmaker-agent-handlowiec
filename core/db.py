from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
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
    DEAD_END = "dead_end"  # research/enrichment nie znalazly kontaktu - skip do recheck


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
    ENRICH_LEAD = "enrich_lead"                # uzupełnij email/telefon dla pojedynczego lead
    BULK_ENRICH_LEADS = "bulk_enrich_leads"    # batch enrichment leadów bez kontaktu
    GENERATE_DRAFT = "generate_draft"          # draft dla lead_id
    BULK_GENERATE_DRAFTS = "bulk_generate_drafts"
    SEND_DRAFT = "send_draft"                  # push do Woodpecker
    POLL_WOODPECKER = "poll_woodpecker"        # update statusów replied/bounced
    AUTONOMOUS_DISCOVERY = "autonomous_discovery"  # Faza 4: cel + budzet, sam iteruje


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
    # Enrichment tracking: kiedy ostatnio probowalismy znalezc email/phone.
    # (uwaga: created_at index ponizej, dla sparkline range queries)
    # Dead-end leady recheckujemy po 90 dniach (firmy aktualizuja wizytowki).
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Soft-delete: user usuwa lead -> deleted_at = now(), lead znika z list/dashboard
    # ale zostaje w DB przez RECYCLE_BIN_DAYS dni (7 dzien). Worker auto-purgeuje
    # leady ze starym deleted_at -> hard delete (cascade na drafty). User moze
    # restore (deleted_at = None) zanim auto-purge ich tknie.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    drafts: Mapped[list["EmailDraft"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Compound idx: lead lists + sparklines (WHERE workspace_id = ? ORDER BY created_at DESC)
        Index("ix_leads_workspace_created", "workspace_id", "created_at"),
        # Trash view: WHERE workspace_id = ? AND deleted_at IS NOT NULL ORDER BY deleted_at DESC
        # + auto-purge query: WHERE deleted_at < cutoff (worker tick co 1h)
        Index("ix_leads_workspace_deleted", "workspace_id", "deleted_at"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)

    lead: Mapped["Lead"] = relationship(back_populates="drafts")

    __table_args__ = (
        # list_drafts: WHERE workspace_id = ? AND status = ? ORDER BY created_at DESC
        Index("ix_drafts_workspace_status_created", "workspace_id", "status", "created_at"),
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True,
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # lead_id - dla szybkiego timeline per-lead (klik na lead -> historia).
    # Bez tej kolumny trzeba bylo szukac po payload JSON co jest wolne na
    # Postgres bez funkcjonalnego indeksu.
    # ondelete=SET NULL: lead permanent delete (kosz auto-purge LUB user permanent)
    # nie moze rzucac IntegrityError bo eventy istnieja. Stare Eventy pozostaja
    # w timeline workspace (workspace_id ich nadal trzyma), tylko trace do leada
    # gubia - lead i tak zniknal.
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True,
    )
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
    __table_args__ = (
        # Compound index dla claim_next_job: WHERE status=pending ORDER BY created_at LIMIT 1
        # Eliminuje seq scan na rosnacej tabeli Job (tysiace jobow przy skali).
        Index("ix_jobs_status_created", "status", "created_at"),
        # Compound index dla list_jobs (status + workspace filter)
        Index("ix_jobs_workspace_status", "workspace_id", "status"),
    )

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


class PatrolSchedule(Base):
    """Autonomiczny agent: co frequency_hours sam pozyskuje + researchuje + draftuje.

    User konfiguruje raz (segment, lokalizacje, cap dzienny), agent leci w tle
    24/7 dopoki enabled=True. Worker w petli loop_forever co 60s sprawdza:
        - dla kazdego enabled PatrolSchedule gdzie next_run_at <= now()
        - tworzy DISCOVERY_PIPELINE job z config patrola
        - aktualizuje last_run_at + next_run_at = now + frequency_hours

    runs_today + day_anchor pilnuja zeby nie przekraczac cap_per_day -
    np. agent 4h frequency = 6 startow/dobe, ale cap moze ograniczyc do 3.
    """
    __tablename__ = "patrol_schedules"
    __table_args__ = (
        Index("ix_patrol_workspace_enabled", "workspace_id", "enabled"),
        Index("ix_patrol_next_run", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    name: Mapped[str] = mapped_column(String(255))  # "Sklepy plastyczne Krakow"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Config - co i jak szukac
    segments: Mapped[list] = mapped_column(JSON, default=list)       # ["sklep_plastyczny"]
    locations: Mapped[list] = mapped_column(JSON, default=list)      # ["Krakow", "Warszawa"]
    sources: Mapped[list] = mapped_column(JSON, default=list)        # ["google_places", "apify"]
    custom_target: Mapped[str | None] = mapped_column(Text)          # opcjonalny opis

    max_per_run: Mapped[int] = mapped_column(Integer, default=10)    # ile leadow / 1 tick
    cap_per_day: Mapped[int] = mapped_column(Integer, default=30)    # twardy limit dzienny
    frequency_hours: Mapped[int] = mapped_column(Integer, default=12)# co ile godzin tick
    relevance_threshold: Mapped[int] = mapped_column(Integer, default=6)
    auto_draft_threshold: Mapped[int | None] = mapped_column(Integer)  # >=N -> generuj draft

    # Bookkeeping
    runs_today: Mapped[int] = mapped_column(Integer, default=0)
    day_anchor: Mapped[datetime | None] = mapped_column(DateTime)   # data ostatniego reset cap
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    total_leads_found: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DiscoveryRun(Base):
    """Cache + audit log dla discovery query.

    Klucz cacheu: query_hash = sha256(segment + location + sources_sorted).
    Przed kazdym Apify/Places call sprawdzamy czy w ostatnich N dni byl
    identyczny query - jak tak, zwracamy cached_places z bazy zamiast
    palić kredytu.

    Zapisujemy też metadane (cost_usd, leads_added) do raportowania
    "ile zaoszczędziłeś przez cache" + ROI per workspace.
    """
    __tablename__ = "discovery_runs"
    __table_args__ = (
        # Cache lookup: WHERE workspace_id = ? AND query_hash = ? ORDER BY run_at DESC
        Index("ix_discovery_runs_ws_hash_at", "workspace_id", "query_hash", "run_at"),
        # History panel: WHERE workspace_id = ? ORDER BY run_at DESC
        Index("ix_discovery_runs_ws_at", "workspace_id", "run_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Cache key - sha256(segment|location|sources_csv). Stale 64-char hex.
    query_hash: Mapped[str] = mapped_column(String(64), index=True)

    # Discovery params (for history display + replay)
    segment: Mapped[str] = mapped_column(String(50))
    location: Mapped[str | None] = mapped_column(String(255))
    sources: Mapped[list] = mapped_column(JSON, default=list)
    query: Mapped[str | None] = mapped_column(Text)  # full query string sent to sources
    custom_description: Mapped[str | None] = mapped_column(Text)

    # Results snapshot - lista DiscoveredPlace.model_dump() dla cache replay.
    # Nullable bo czasem run się wywala (error) - mamy wpis audit ale brak danych.
    cached_places: Mapped[list | None] = mapped_column(JSON)

    # Stats
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    leads_added: Mapped[int] = mapped_column(Integer, default=0)  # ile nowych po researchu
    cost_usd: Mapped[float | None] = mapped_column(Float)         # szacunkowy koszt
    error: Mapped[str | None] = mapped_column(Text)               # jak run padl

    # job_id - tag laczacy DiscoveryRun z autonomous_discovery jobem ktory go
    # utworzyl. Pozwala zgrupowac historie: 1 autonomous job = N (segment,city)
    # runow -> w panelu Historia pokazujemy 1 zwijany wpis zamiast 350 wierszy.
    # Nullable: manual discovery_search nie ustawia (single run = single wpis).
    job_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)

    run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class DiscoveryExclusion(Base):
    """Lista wykluczen per workspace - co nie ma sensu skanowac.

    Typy:
      'domain'        - znormalizowana domena ktora nigdy nie pasuje
                        (np. "rossmann.pl" - sieć drogerii, nie nasz target)
      'brand'         - nazwa marki ktora chcemy auto-skip'owac
      'city_segment'  - kombinacja (city, segment) gdzie 0 nowych firm
                        po 2+ runach - oszczedzamy kredyt

    User dodaje recznie z drawera leada ("Wyklucz tę firmę z przyszlych
    discoveries") albo system auto-dodaje po 2 nieudanych runach
    (Faza 2.1 - dorobimy potem).
    """
    __tablename__ = "discovery_exclusions"
    __table_args__ = (
        Index("ix_disco_excl_ws_type", "workspace_id", "exclusion_type"),
        # Unique zeby nie duplikowac wpisow per (workspace, type, value)
        Index("ix_disco_excl_unique", "workspace_id", "exclusion_type", "value", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    exclusion_type: Mapped[str] = mapped_column(String(20))  # domain / brand / city_segment
    value: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)  # "sieć Rossmanna", "auto: 0 nowych w 2 runach"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ─── Engine + session ────────────────────────────────────────────────────

# Engine config: dla Postgres - skalowalne defaulty.
# pool_size=5: per-proces base pool (5 conn ready)
# max_overflow=10: dodatkowe conn pod load (max 15 total per proces)
# pool_pre_ping=True: testuje conn przed uzyciem - eliminuje "stale connection"
#   errory gdy Postgres zerwie idle conn (Railway/Heroku robi to co ~5min)
# pool_recycle=1800: forsuje recycle co 30min - prevents pg_terminate_backend
# Dla SQLite (lokalnie) te opcje sa ignorowane (single-file DB).
_engine_kwargs: dict[str, object] = {"echo": False, "future": True}
if str(settings.db_url).startswith("postgres"):
    _engine_kwargs.update({
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    })
_engine = create_engine(settings.db_url, **_engine_kwargs)

# expire_on_commit=False: po session.commit() obiekty NIE sa expired - atrybuty
# pozostaja dostepne bez extra SELECT. Eliminuje DetachedInstanceError gdy ORM
# obiekt jest uzywany po commitcie. Worker handlery robia commit co iteracje -
# bez tego kazdy job.workspace_id po commit = nowy round trip do DB.
SessionLocal = sessionmaker(
    bind=_engine, autoflush=False, autocommit=False, future=True,
    expire_on_commit=False,
)


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
    _backfill_lead_status()
    _cleanup_junk_emails()  # One-shot: wyczysc stare leady ze smieciowymi mailami


def _backfill_lead_status() -> None:
    """One-shot backfill: leady ze statusem 'drafted'/'approved' ale BEZ
    aktywnego (non-rejected) draftu wracaja do 'researched'.

    Powod: do tego commita reject_draft NIE cofal lead.status. Wynik: leady
    wisialy w 'drafted' mimo ze ich jedyny draft byl rejected -> UI mylil
    + nie dawal generowac nowego draftu (bo "lead juz ma draft").

    Idempotent: po backfille i fix endpoint'a nigdy nie znajdzie wiecej
    leadow do cofniecia.
    """
    import logging
    log = logging.getLogger("ecombinat.backfill")
    from sqlalchemy import select, update, func as sa_func
    try:
        with SessionLocal() as session:
            # Znajdz drafted/approved leady BEZ jakiegokolwiek non-rejected draftu.
            # Subquery: lead_ids ktore MAJA aktywny draft.
            active_lead_ids_sq = (
                select(EmailDraft.lead_id).where(
                    EmailDraft.status != "rejected",
                ).distinct().subquery()
            )
            stmt = (
                update(Lead)
                .where(
                    Lead.status.in_(["drafted", "approved"]),
                    Lead.id.notin_(select(active_lead_ids_sq.c.lead_id)),
                )
                .values(status="researched")
            )
            result = session.execute(stmt)
            session.commit()
            if result.rowcount and result.rowcount > 0:
                log.info(
                    f"Backfill: cofnieto status do 'researched' dla "
                    f"{result.rowcount} leadow (wszystkie ich drafty rejected)"
                )
    except Exception as exc:
        log.warning(f"Backfill lead.status failed (non-critical): {exc}")


def _cleanup_junk_emails() -> None:
    """Migracja: wyczysc Lead.email gdzie wartosc NIE jest poprawnym
    biznesowym emailem (fragmenty JS/HTML/URL sparsowane jak email).

    Przyklady syfu ktory wpadl: d@e.gettime, cre@ivecommons.org,
    secure.grav@ar.com, 29818881.two_step_verific@ion.pre,
    https%3a%2f%2fsztuk@worzenia.pl, ko*****@*********ry.pl.

    Uzywa is_valid_business_email (TLD whitelist + struktura) - znacznie
    scislejsze niz stary _is_junk_email blacklist. Czysci email = NULL,
    lead zostaje (mozna go potem re-research'owac z drawera).

    Idempotent: po przebiegu syf zastapiony None. Drugi run no-op (poprawne
    emaile zostaja).
    """
    import logging
    log = logging.getLogger("ecombinat.cleanup")
    try:
        from core.email_validate import is_valid_business_email
    except Exception:
        return

    try:
        with _engine.begin() as conn:
            # Bierzemy wszystkie leady z niepusty email
            rows = conn.execute(text(
                "SELECT id, email FROM leads WHERE email IS NOT NULL AND email != ''"
            )).all()
            junk_ids: list[int] = []
            for lead_id, email in rows:
                if not is_valid_business_email(email):
                    junk_ids.append(lead_id)
            if junk_ids:
                # Update w batchach po 500 (Postgres ma limit parametrow w IN)
                for i in range(0, len(junk_ids), 500):
                    batch = junk_ids[i:i + 500]
                    placeholders = ",".join(str(x) for x in batch)
                    conn.execute(text(
                        f"UPDATE leads SET email = NULL WHERE id IN ({placeholders})"
                    ))
                log.info(
                    f"Junk email cleanup: cleared email on {len(junk_ids)} leads "
                    f"(niepoprawne emaile - fragmenty JS/URL/maski, walidacja is_valid_business_email)"
                )
    except Exception as exc:
        log.warning(f"Junk email cleanup failed (non-critical): {exc}")


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
        ("leads", "last_enriched_at", "TIMESTAMP" if is_pg else "DATETIME"),
        ("leads", "deleted_at", "TIMESTAMP" if is_pg else "DATETIME"),
        ("email_drafts", "workspace_id", "INTEGER"),
        ("email_drafts", "snippet4", "TEXT"),
        ("email_drafts", "snippet5", "TEXT"),
        ("email_drafts", "edited_by_user", "BOOLEAN DEFAULT FALSE" if is_pg else "INTEGER DEFAULT 0"),
        ("events", "workspace_id", "INTEGER"),
        ("events", "user_id", "INTEGER"),
        ("events", "lead_id", "INTEGER"),
        ("events", "payload", "JSON" if is_pg else "TEXT"),
        ("discovery_runs", "job_id", "INTEGER"),
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

    # Dorzuc brakujace indeksy na istniejacych tabelach. create_all() ich
    # nie tworzy bo tabele juz istnieja. Pojedynczy CREATE INDEX IF NOT EXISTS
    # jest idempotentny i szybki (no-op gdy juz jest).
    indexes_to_create = [
        # Worker queue claim_next_job
        ("ix_jobs_status_created", "jobs", "(status, created_at)"),
        ("ix_jobs_workspace_status", "jobs", "(workspace_id, status)"),
        # Lead lists + sparklines
        ("ix_leads_workspace_created", "leads", "(workspace_id, created_at)"),
        ("ix_leads_created_at", "leads", "(created_at)"),
        # Trash view + worker auto-purge
        ("ix_leads_workspace_deleted", "leads", "(workspace_id, deleted_at)"),
        # Draft lists
        ("ix_drafts_workspace_status_created", "email_drafts", "(workspace_id, status, created_at)"),
        ("ix_email_drafts_created_at", "email_drafts", "(created_at)"),
        # Event timeline per-lead
        ("ix_events_lead_id", "events", "(lead_id)"),
        # Discovery cache + history
        ("ix_discovery_runs_ws_hash_at", "discovery_runs", "(workspace_id, query_hash, run_at)"),
        ("ix_discovery_runs_ws_at", "discovery_runs", "(workspace_id, run_at)"),
        # Discovery exclusions
        ("ix_disco_excl_ws_type", "discovery_exclusions", "(workspace_id, exclusion_type)"),
    ]
    idx_added = 0
    for idx_name, table, cols in indexes_to_create:
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} {cols}"
                ))
                idx_added += 1
        except Exception as exc:
            log.warning(f"CREATE INDEX {idx_name} skipped: {exc}")
    if idx_added:
        log.info(f"Schema migration: ensured {idx_added} indexes")


def _ensure_default_workspace() -> None:
    """Idempotent: tworzy admin user + jego workspace + member.

    Każdy krok w OSOBNEJ transakcji - jeśli np. workspace ma slug conflict
    (ktoś z testowych userów zajął "default"), admin i tak zostaje w bazie.

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

    # KROK 1: Admin user (osobna transakcja - jak workspace failuje admin zostaje)
    admin_id: int | None = None
    try:
        with SessionLocal() as session:
            admin = session.execute(
                select(User).where(User.email == admin_email)
            ).scalar_one_or_none()
            if admin is None:
                from web.auth import hash_password
                pw_to_use = admin_pw or "ecombinat-admin"
                admin = User(
                    email=admin_email,
                    password_hash=hash_password(pw_to_use),
                    name="Admin",
                    is_admin=True,
                )
                session.add(admin)
                session.commit()
                log.info(f"Admin user CREATED: {admin_email}")
            elif admin_pw:
                # Admin istnieje - sync hasla z env jesli mismatch.
                from web.auth import hash_password, verify_password
                try:
                    matches = verify_password(admin_pw, admin.password_hash)
                except Exception:
                    matches = False
                if not matches:
                    admin.password_hash = hash_password(admin_pw)
                    session.commit()
                    log.warning(f"Admin password RESET from env for {admin_email}")
                else:
                    log.info(f"Admin password OK for {admin_email}")
            else:
                log.warning(
                    f"Admin user {admin_email} exists but ADMIN_PASSWORD env NOT SET - "
                    f"login impossible until you set ADMIN_PASSWORD env var"
                )
            admin_id = admin.id
    except Exception as exc:
        log.error(f"Admin user setup FAILED: {exc}", exc_info=True)
        return

    if admin_id is None:
        return

    # KROK 2: Workspace dla admina (z unique-slug fallback)
    ws_id: int | None = None
    try:
        with SessionLocal() as session:
            # Sprawdz czy admin ma juz JAKIKOLWIEK workspace
            ws = session.execute(
                select(Workspace).where(Workspace.owner_user_id == admin_id)
                .order_by(Workspace.created_at).limit(1)
            ).scalar_one_or_none()
            if ws is None:
                # Znajdz unikalny slug. Preferowany: "default", fallback "ecombinat-admin-N"
                base_slugs = ["default", "ecombinat-admin", "admin-workspace"]
                slug = None
                for candidate in base_slugs:
                    existing = session.execute(
                        select(Workspace).where(Workspace.slug == candidate)
                    ).scalar_one_or_none()
                    if existing is None:
                        slug = candidate
                        break
                if slug is None:
                    # All taken - generuj z licznikiem
                    n = 2
                    while True:
                        slug_try = f"ecombinat-admin-{n}"
                        existing = session.execute(
                            select(Workspace).where(Workspace.slug == slug_try)
                        ).scalar_one_or_none()
                        if existing is None:
                            slug = slug_try
                            break
                        n += 1
                        if n > 999:
                            log.error("Cannot find unique slug for admin workspace")
                            return
                ws = Workspace(
                    name="Default Workspace",
                    slug=slug,
                    owner_user_id=admin_id,
                    plan="enterprise",
                    monthly_credits=99999,
                )
                session.add(ws)
                session.commit()
                log.info(f"Admin workspace CREATED slug={slug}")
            ws_id = ws.id
    except Exception as exc:
        log.error(f"Admin workspace setup FAILED: {exc}", exc_info=True)
        return

    if ws_id is None:
        return

    # KROK 3: WorkspaceMember (idempotent)
    try:
        with SessionLocal() as session:
            member = session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == ws_id,
                    WorkspaceMember.user_id == admin_id,
                )
            ).scalar_one_or_none()
            if member is None:
                session.add(WorkspaceMember(
                    workspace_id=ws_id,
                    user_id=admin_id,
                    role=WorkspaceRole.OWNER.value,
                ))
                session.commit()
                log.info(f"Admin WorkspaceMember CREATED for ws #{ws_id}")
    except Exception as exc:
        log.error(f"Admin WorkspaceMember setup FAILED: {exc}", exc_info=True)
        return

    # KROK 4: Migracja starych danych (osobna transakcja, niekrytyczna)
    try:
        with SessionLocal() as session:
            session.execute(update(Lead).where(Lead.workspace_id.is_(None)).values(workspace_id=ws_id))
            session.execute(update(EmailDraft).where(EmailDraft.workspace_id.is_(None)).values(workspace_id=ws_id))
            session.execute(update(Event).where(Event.workspace_id.is_(None)).values(workspace_id=ws_id))
            session.commit()
    except Exception as exc:
        log.warning(f"Legacy data migration to admin workspace failed (non-critical): {exc}")


def get_session():
    return SessionLocal()
