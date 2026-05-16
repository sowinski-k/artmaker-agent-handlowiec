"""Ecombinat FastAPI backend - multi-tenant SaaS.

Wszystkie operacje są kontekstualizowane przez workspace_id (RLS w warstwie
aplikacji). Każdy klient widzi TYLKO swoje dane. Auth przez bcrypt hashowane
hasła + signed Bearer tokens (itsdangerous).

Asynchroniczne operacje (discovery, research, generate) idą przez Job queue
do osobnego worker process'u - user może wylogować się, jobs lecą dalej.

Bezpieczeństwo:
  - Rate limit per IP (5 prób login / 5 min)
  - bcrypt password hashing (cost 12)
  - Security headers (HSTS, X-Frame-Options, CSP-friendly)
  - Tenant isolation: każdy query filter by workspace_id
  - Audit log per workspace (Event table)
  - Generic error responses (zero stack trace leak)
  - HTTPS-only cookies w prod, samesite=none for cross-origin
"""
from __future__ import annotations

import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import json as _json

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session, joinedload

from core.db import (
    DiscoveryExclusion,
    DiscoveryRun,
    DraftStatus,
    EmailDraft,
    Event,
    Job,
    JobStatus,
    JobType,
    Lead,
    LeadSegment,
    LeadStatus,
    PatrolSchedule,
    SessionLocal,
    User,
    Workspace,
    WorkspaceMember,
    init_db,
)
from web.auth import (
    COOKIE_MAX_AGE,
    COOKIE_NAME,
    CurrentUser,
    get_current_user,
    make_token,
    register_user,
    validate_email,
    verify_password,
    verify_token,
)
from web.jobs_dispatcher import count_active_jobs, create_job, find_active_job, serialize_job

# Maks ile DISCOVERY/BULK_RESEARCH jobow moze byc rownolegle/w queue per workspace.
# Worker ma thread pool (WORKER_THREADS, default 3) - przetwarza rownolegle.
# Ten cap to gorny limit zeby user nie zalal queue 100+ jobami naraz (cost guard).
MAX_CONCURRENT_HEAVY_JOBS = int(os.getenv("MAX_CONCURRENT_HEAVY_JOBS") or 10)


# ─── ROI: stawki i czasy ręcznej pracy per rok ──────────────────────────
#
# AUTOMATYKA: backend sam wybiera kwoty na podstawie current year.
# Brak env vars do konfiguracji - user nic nie ustawia.
# Co rok aktualizujemy te dicty (1 linijka + deploy) gdy GUS ogłosi nowe
# stawki.
#
# Źródła stawek 2026:
# - Najniższa krajowa miesięczna: 4806 zł brutto (Rozporządzenie RM z 11.09.2025)
# - **Minimalna stawka godzinowa: 31.40 zł brutto** - to OFICJALNA stawka
#   ustawowa, NIE 4806/168 = 28.6. Stawka godzinowa rośnie szybciej niż
#   miesięczna (różnica idzie do tych co pracują na umowie zleceniu - placa
#   za realnie przepracowane godziny vs etat z urlopami).
# - Netto z 4806 brutto ≈ 3621 zł "na rękę" (po PIT, ZUS pracownika, składkach)
# - Employer cost mult 1.2305: brutto + ZUS pracodawcy (emerytalna 9.76%,
#   rentowa 6.5%, wypadkowa ~1.67%, FP 2.45%, FGŚP 0.1%) ≈ 20.48% narzutu
#   (rezerwa urlopowa + chorobowe + benefity to osobny koszt, NIE wliczamy
#   bo to fluktuuje per firma).
# - Stawka handlowca B2B 2025/2026: junior 50-60, mid 70-90, senior 100+
#   Bierzemy mid jako fair estymata średniego rynku.

# Minimum wage history + future projections (miesięczna brutto)
MIN_WAGE_BY_YEAR: dict[int, float] = {
    2024: 4242.0,
    2025: 4666.0,
    2026: 4806.0,  # Rozp. RM z 11.09.2025
    # 2027+: aktualizuj gdy GUS ogłosi
}

# Minimalna stawka godzinowa BRUTTO (ustawowa) per rok
# 2026: 31.40 zł/h (oficjalna, w Rozp. RM z 11.09.2025)
MIN_WAGE_HOURLY_BY_YEAR: dict[int, float] = {
    2024: 27.70,
    2025: 30.50,
    2026: 31.40,  # oficjalna stawka, nie wyliczona z miesięcznej
}

# Netto miesięczne dla najniższej krajowej (po PIT + ZUS pracownika)
# 2026: 3621 zł "na rękę" przy 4806 brutto
MIN_WAGE_NET_MONTHLY_BY_YEAR: dict[int, float] = {
    2024: 3262.0,
    2025: 3510.0,
    2026: 3621.0,
}

# Stawka handlowca B2B per rok (rynek - subiektywne, można dostosować)
SALES_RATE_BY_YEAR: dict[int, float] = {
    2024: 55.0,
    2025: 58.0,
    2026: 60.0,
    # 2027+: aktualizuj wedle rynku
}

# Mnożnik koszt pracodawcy brutto -> realny koszt etatu (z ZUS pracodawcy)
# 20.48% narzutu = ZUS pracodawcy (emerytalna+rentowa+wypadkowa+FP+FGŚP)
EMPLOYER_COST_MULTIPLIER = 1.2048

# Hours per month (Kodeks Pracy art. 130)
HOURS_PER_MONTH = 168

# Czasy ręcznej pracy per zadanie (z praktyki - relatywnie stabilne między latami)
# UWAGA: user-facing labelki sa w endpoint /api/dashboard ponizej (breakdown).
# Tu trzymamy tylko KEY -> czas. User nie widzi tych keys.
LABOR_TIME_MINUTES: dict[str, float] = {
    "research": 8.0,        # sprawdzenie firmy: kto to, czym sie zajmuje, czy pasuje
    "enrich_success": 2.0,  # znalezienie adresu mailowego na stronie (tylko gdy success)
    "draft": 15.0,          # napisanie spersonalizowanego maila
    "sent": 1.0,            # wyslanie + zapis w historii
}


def _get_roi_rates_for_today() -> dict[str, float]:
    """Auto-pick stawki na bieżący rok. Bez env, bez konfiguracji u user'a.

    Jak rok nie jest w mappingu (np. uruchamiamy w 2028 a ostatnio
    dodaliśmy 2026), bierzemy ostatni dostępny rok (fallback do
    'najlepszej znanej wartości').
    """
    current_year = datetime.now(timezone.utc).year
    latest = max(MIN_WAGE_BY_YEAR.keys())
    pick_year = current_year if current_year in MIN_WAGE_BY_YEAR else latest

    min_wage_monthly = MIN_WAGE_BY_YEAR[pick_year]
    # Stawka godzinowa: PREFEROWANA jest oficjalna ustawowa (31.40 dla 2026).
    # Fallback do wyliczenia z miesięcznej dla starszych lat bez oficjalnej.
    min_wage_h = MIN_WAGE_HOURLY_BY_YEAR.get(
        pick_year,
        round(min_wage_monthly / HOURS_PER_MONTH, 2),
    )
    min_wage_net_monthly = MIN_WAGE_NET_MONTHLY_BY_YEAR.get(
        pick_year,
        round(min_wage_monthly * 0.755, 0),  # heurystyka: 75.5% brutto -> netto
    )
    sales_rate = SALES_RATE_BY_YEAR.get(
        pick_year,
        SALES_RATE_BY_YEAR[max(SALES_RATE_BY_YEAR.keys())],
    )
    return {
        "year": pick_year,
        "min_wage_monthly": min_wage_monthly,
        "min_wage_monthly_net": min_wage_net_monthly,
        "min_wage_h": min_wage_h,
        "employer_mult": EMPLOYER_COST_MULTIPLIER,
        "sales_rate_h": sales_rate,
        "min_per_research": LABOR_TIME_MINUTES["research"],
        "min_per_enrich": LABOR_TIME_MINUTES["enrich_success"],
        "min_per_draft": LABOR_TIME_MINUTES["draft"],
        "min_per_sent": LABOR_TIME_MINUTES["sent"],
    }


# ─── Config ──────────────────────────────────────────────────────────────

_origins_env = (os.getenv("FRONTEND_ORIGINS") or "http://localhost:3000").strip()
ALLOWED_ORIGINS = ["*"] if _origins_env == "*" else [
    o.strip() for o in _origins_env.split(",") if o.strip()
]
IS_PROD = os.getenv("RAILWAY_ENVIRONMENT") is not None

# COOKIE_DOMAIN: ustaw na ".twojadomena.pl" zeby cookie bylo shared miedzy
# app.twojadomena.pl (frontend) i api.twojadomena.pl (backend) - WTEDY
# mozna uzyc SameSite=Lax (silniejszy niz None) i zrezygnowac z Bearer headera
# w localStorage. Bez tego (cross-domain railway.app + custom domain frontend)
# musimy uzywac SameSite=None + Secure - dziala ale slabszy CSRF guard.
COOKIE_DOMAIN = (os.getenv("COOKIE_DOMAIN") or "").strip() or None

# COOKIE_SAMESITE pozwala wymusic 'lax' / 'strict' jak masz subdomena setup
# (zob. COOKIE_DOMAIN). Default: 'none' w prod (cross-origin), 'lax' w dev.
_samesite_env = (os.getenv("COOKIE_SAMESITE") or "").strip().lower()
COOKIE_SAMESITE = _samesite_env if _samesite_env in {"lax", "strict", "none"} else (
    "none" if IS_PROD else "lax"
)
# Secure musi byc True dla SameSite=None (wymog przegladarki) oraz w prod.
COOKIE_SECURE = IS_PROD or COOKIE_SAMESITE == "none"


def _set_session_cookie(response: Response, token: str) -> None:
    """Pojedynczy helper do ustawiania ciasteczka - uzywany w register/login.
    Centralizuje flagi zeby logout/set/delete uzywaly tych samych ustawien.
    """
    response.set_cookie(
        key=COOKIE_NAME, value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        domain=COOKIE_DOMAIN,
        path="/",
    )


limiter = Limiter(key_func=get_remote_address)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ecombinat")

# Sentry init musi byc PRZED app = FastAPI(...) zeby lapal startup errory.
from core.observability import init_sentry
from core.serialize import iso_utc
init_sentry("web")


# ─── App lifespan ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        init_db()
        log.info("DB initialized")
    except Exception as exc:
        log.exception(f"DB init failed: {exc}")
    yield


app = FastAPI(title="Ecombinat API", version="0.4.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if IS_PROD:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Nieprawidłowe dane wejściowe."})


@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    log.exception(f"Unhandled error on {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Wewnętrzny błąd serwera."})


# ─── Audit log helper ────────────────────────────────────────────────────

def _log_event(workspace_id: int | None, user_id: int | None,
               level: str, source: str, event_type: str, message: str) -> None:
    try:
        with SessionLocal() as session:
            session.add(Event(
                workspace_id=workspace_id, user_id=user_id,
                level=level, source=source, type=event_type,
                message=message[:1000],
            ))
            session.commit()
    except Exception as exc:
        log.warning(f"Audit log failed: {exc}")


# ─── Schemas ────────────────────────────────────────────────────────────

class RegisterIn(BaseModel):
    email: str
    password: str
    name: str | None = None
    workspace_name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class AuthOut(BaseModel):
    token: str
    user: dict[str, Any]
    workspace: dict[str, Any]


class MeOut(BaseModel):
    user: dict[str, Any]
    workspace: dict[str, Any]


# ─── Health / version ────────────────────────────────────────────────────

@app.get("/")
def root() -> dict[str, Any]:
    return {"app": "ecombinat-api", "version": "0.4.0", "status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/_health/worker")
def worker_health() -> dict[str, Any]:
    """Sprawdz czy worker zyje - czyta ostatni Event(type='worker.heartbeat').

    Worker pisze heartbeat co 60s (WORKER_HEARTBEAT_INTERVAL). Jak ostatni
    heartbeat > 120s temu, worker padl albo zawiesil sie. Endpoint public
    (no auth) zeby latwo monitorowac z zewnatrz (Railway healthcheck,
    UptimeRobot, prosty cron).

    Status:
      ok      - heartbeat < 120s (worker zdrowy)
      warn    - 120-300s (mozliwy zwis, ostrzezenie)
      down    - >300s LUB brak heartbeatu w ogole
    """
    threshold_warn_s = float(os.getenv("WORKER_HEALTH_WARN_S", "120"))
    threshold_down_s = float(os.getenv("WORKER_HEALTH_DOWN_S", "300"))
    try:
        with SessionLocal() as session:
            last = session.execute(
                select(Event)
                .where(Event.type == "worker.heartbeat")
                .order_by(Event.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
    except Exception as exc:
        return {"status": "unknown", "error": str(exc)[:200]}

    if last is None:
        return {"status": "down", "reason": "no heartbeat ever recorded"}

    now = datetime.now(timezone.utc)
    last_at = last.created_at
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    age_s = (now - last_at).total_seconds()

    if age_s > threshold_down_s:
        status_ = "down"
    elif age_s > threshold_warn_s:
        status_ = "warn"
    else:
        status_ = "ok"
    return {
        "status": status_,
        "last_heartbeat_at": iso_utc(last_at),
        "age_seconds": round(age_s, 1),
        "warn_threshold_s": threshold_warn_s,
        "down_threshold_s": threshold_down_s,
    }


@app.get("/api/_diag")
def diagnostics() -> dict[str, Any]:
    """Diagnostic endpoint - bezpieczny do public bo NIE leakuje wartosci sekretow.

    Zwraca tylko czy env vars sa ustawione + czy admin user istnieje w bazie.
    Pomocne kiedy login admina nie dziala - widac czy env doszedl, czy DB ma usera.
    """
    admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    admin_pw = (os.getenv("APP_PASSWORD") or os.getenv("ADMIN_PASSWORD") or "").strip()
    out = {
        "admin_email_env_set": bool(admin_email),
        # Preview usuniety - leakowal pierwsze znaki emaila (brute-forceable).
        "admin_password_env_set": bool(admin_pw),
        "admin_password_length": len(admin_pw) if admin_pw else 0,
        "admin_user_in_db": False,
        "admin_workspace_count": 0,
        "total_users": 0,
        "total_workspaces": 0,
        "db_url_kind": "postgres" if not str(__import__("core.config", fromlist=["settings"]).settings.db_url).startswith("sqlite") else "sqlite",
    }
    try:
        with SessionLocal() as session:
            out["total_users"] = int(session.scalar(select(func.count(User.id))) or 0)
            out["total_workspaces"] = int(session.scalar(select(func.count(Workspace.id))) or 0)
            if admin_email:
                admin = session.execute(select(User).where(User.email == admin_email)).scalar_one_or_none()
                if admin:
                    out["admin_user_in_db"] = True
                    out["admin_user_is_admin"] = bool(admin.is_admin)
                    out["admin_user_active"] = bool(admin.is_active)
                    out["admin_workspace_count"] = int(session.scalar(
                        select(func.count(WorkspaceMember.id)).where(WorkspaceMember.user_id == admin.id)
                    ) or 0)
    except Exception as exc:
        out["error"] = str(exc)[:200]
    return out


# ─── Auth ────────────────────────────────────────────────────────────────

@app.post("/api/auth/register", response_model=AuthOut)
@limiter.limit("10/hour")
def register(request: Request, payload: RegisterIn, response: Response) -> AuthOut:
    """Rejestracja: tworzy User + Workspace (owner). Auto-login (zwraca token)."""
    if not validate_email(payload.email):
        raise HTTPException(status_code=400, detail="Nieprawidłowy email.")
    with SessionLocal() as session:
        user, ws = register_user(
            session,
            email=payload.email,
            password=payload.password,
            name=payload.name,
            workspace_name=payload.workspace_name,
        )
        token = make_token(user.id, ws.id)
        # Cookie httpOnly (XSS-safe) - obok Bearer token w response
        _set_session_cookie(response, token)
        _log_event(ws.id, user.id, "INFO", "auth", "user_registered",
                   f"New user registered: {user.email}")
        return AuthOut(
            token=token,
            user={"id": user.id, "email": user.email, "name": user.name,
                  "is_admin": user.is_admin},
            workspace={"id": ws.id, "name": ws.name, "slug": ws.slug,
                       "plan": ws.plan, "credits": ws.monthly_credits,
                       "used_credits": ws.used_credits},
        )


@app.post("/api/auth/login", response_model=AuthOut)
@limiter.limit("5/5minutes")
def login(request: Request, payload: LoginIn, response: Response) -> AuthOut:
    email = payload.email.strip().lower()
    with SessionLocal() as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None or not verify_password(payload.password, user.password_hash):
            _log_event(None, None, "WARNING", "auth", "login_failed",
                       f"Failed login from {get_remote_address(request)} for {email}")
            raise HTTPException(status_code=401, detail="Nieprawidłowy email lub hasło.")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Konto nieaktywne.")

        # Wybierz najnowszy workspace (jeśli user ma kilka)
        ws = session.execute(
            select(Workspace)
            .join(WorkspaceMember, Workspace.id == WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user.id)
            .order_by(Workspace.created_at.desc())
        ).scalars().first()

        if ws is None:
            # Defensywnie: owned ale brak member - sprawdź ownership
            ws = session.execute(
                select(Workspace).where(Workspace.owner_user_id == user.id)
                .order_by(Workspace.created_at.desc())
            ).scalars().first()

        if ws is None:
            log.error(f"User {user.id} has no workspace - creating fallback default")
            from web.auth import slugify
            ws_name = (user.name or user.email.split("@")[0])[:255] or "Workspace"
            base_slug = slugify(ws_name)
            slug = base_slug
            n = 1
            while session.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none():
                n += 1
                slug = f"{base_slug}-{n}"
            ws = Workspace(name=ws_name, slug=slug, owner_user_id=user.id, plan="free", monthly_credits=100)
            session.add(ws)
            session.flush()
            session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
            session.commit()

        user.last_login_at = datetime.now(timezone.utc)
        session.commit()

        token = make_token(user.id, ws.id)
        _set_session_cookie(response, token)
        _log_event(ws.id, user.id, "INFO", "auth", "login_ok",
                   f"Login OK for {user.email}")
        return AuthOut(
            token=token,
            user={"id": user.id, "email": user.email, "name": user.name,
                  "is_admin": user.is_admin},
            workspace={"id": ws.id, "name": ws.name, "slug": ws.slug,
                       "plan": ws.plan, "credits": ws.monthly_credits,
                       "used_credits": ws.used_credits},
        )


@app.post("/api/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    # WAZNE: delete_cookie musi miec te SAME flagi co set_cookie zeby browser
    # faktycznie usunal ciasteczko. Bez samesite/secure/domain browser ignoruje delete.
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        httponly=True,
        domain=COOKIE_DOMAIN,
    )
    return {"ok": True}


@app.get("/api/auth/me", response_model=MeOut)
def me(cur: CurrentUser = Depends(get_current_user)) -> MeOut:
    with SessionLocal() as session:
        ws = session.get(Workspace, cur.workspace_id)
        return MeOut(
            user={"id": cur.user_id, "email": cur.email, "name": cur.name,
                  "is_admin": cur.is_admin},
            workspace={"id": ws.id, "name": ws.name, "slug": ws.slug,
                       "plan": ws.plan, "credits": ws.monthly_credits,
                       "used_credits": ws.used_credits},
        )


# ─── Konto / Ustawienia user ────────────────────────────────────────────

class UpdateProfileIn(BaseModel):
    name: str | None = None


@app.patch("/api/auth/me")
def update_profile(
    payload: UpdateProfileIn, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Edycja profilu - obecnie tylko name. Email zmieniony oddzielnie (wymaga
    weryfikacji - na razie nie udostepniamy)."""
    new_name = (payload.name or "").strip()[:255] or None
    with SessionLocal() as session:
        user = session.get(User, cur.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User nie istnieje.")
        if new_name != user.name:
            user.name = new_name
            session.commit()
            _log_event(cur.workspace_id, cur.user_id, "INFO", "user", "profile_updated",
                       f"User zaktualizowal swoj profil (name)")
        return {"ok": True, "name": new_name}


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/auth/change-password")
@limiter.limit("5/15minutes")
def change_password(
    request: Request, payload: ChangePasswordIn,
    cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Zmiana hasla. Wymaga current_password (anti-CSRF). Re-hash bcrypt."""
    from web.auth import hash_password, validate_password
    ok, err = validate_password(payload.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    with SessionLocal() as session:
        user = session.get(User, cur.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User nie istnieje.")
        if not verify_password(payload.current_password, user.password_hash):
            _log_event(cur.workspace_id, cur.user_id, "WARNING", "auth", "password_change_failed",
                       f"Failed password change attempt - wrong current password")
            raise HTTPException(status_code=401, detail="Aktualne haslo nieprawidlowe.")
        if verify_password(payload.new_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Nowe haslo musi byc inne niz aktualne.")
        user.password_hash = hash_password(payload.new_password)
        session.commit()
        _log_event(cur.workspace_id, cur.user_id, "INFO", "auth", "password_changed",
                   f"User zmienil haslo")
    return {"ok": True}


# ─── Workspace settings ─────────────────────────────────────────────────

class UpdateWorkspaceIn(BaseModel):
    name: str | None = None
    # Owner identity (do sygnatury maili wysylanych przez agenta)
    owner_name: str | None = None
    owner_title: str | None = None
    company_name: str | None = None
    company_website: str | None = None


@app.patch("/api/workspace")
def update_workspace(
    payload: UpdateWorkspaceIn, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Edycja workspace - name + identity owner'a (uzywana w sygnaturach maili).

    Identity przechowywana w Workspace.api_keys (JSON) jako sub-obiekt
    'owner_identity'. Trzymamy razem zeby workspace mial wlasna sygnature -
    settings.owner_name z env to globalny fallback.
    """
    with SessionLocal() as session:
        ws = session.get(Workspace, cur.workspace_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Workspace nie istnieje.")
        # Tylko owner moze edytowac (jak chcesz pozniej dorzucic role MEMBER ze
        # zmiana settings dozwolona - zmien ten check).
        if ws.owner_user_id != cur.user_id and not cur.is_admin:
            raise HTTPException(status_code=403, detail="Tylko owner moze edytowac workspace.")

        changes: list[str] = []
        if payload.name is not None:
            new_name = payload.name.strip()[:255]
            if new_name and new_name != ws.name:
                ws.name = new_name
                changes.append("name")

        # Owner identity - mergujemy w api_keys.owner_identity
        identity_fields = {
            "owner_name": payload.owner_name,
            "owner_title": payload.owner_title,
            "company_name": payload.company_name,
            "company_website": payload.company_website,
        }
        if any(v is not None for v in identity_fields.values()):
            api_keys = dict(ws.api_keys or {})
            identity = dict(api_keys.get("owner_identity", {}))
            for k, v in identity_fields.items():
                if v is not None:
                    identity[k] = v.strip()[:255] if isinstance(v, str) else v
            api_keys["owner_identity"] = identity
            ws.api_keys = api_keys
            changes.append("owner_identity")

        if changes:
            session.commit()
            _log_event(cur.workspace_id, cur.user_id, "INFO", "workspace", "settings_updated",
                       f"Workspace settings zaktualizowane: {', '.join(changes)}")

        identity = (ws.api_keys or {}).get("owner_identity", {}) if ws.api_keys else {}
        return {
            "ok": True,
            "workspace": {
                "id": ws.id, "name": ws.name, "slug": ws.slug,
                "plan": ws.plan, "credits": ws.monthly_credits,
                "used_credits": ws.used_credits,
            },
            "owner_identity": identity,
            "changed": changes,
        }


# ─── API keys per workspace ─────────────────────────────────────────────

# Klucze API ktore user moze ustawic per workspace. Naming dopasowane do env
# (te same nazwy = jasne komu odpowiadaja). Wartosci sa zaszyfrowane/maskowane
# w response (pokazujemy tylko ostatnie 4 znaki).
WORKSPACE_API_KEY_NAMES = [
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "APIFY_API_TOKEN",
    "GOOGLE_PLACES_API_KEY",
    "WOODPECKER_API_KEY",
]


def _mask_key(value: str | None) -> str | None:
    """Pokazuj ostatnie 4 znaki, reszta jako *. None gdy brak."""
    if not value:
        return None
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


@app.get("/api/workspace/api-keys")
def get_workspace_api_keys(
    cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Lista API keys workspace'u + ich stan (set/unset, maska).

    NIE zwraca raw wartosci - tylko ostatnie 4 znaki. User moze tylko nadpisac
    klucz, nie odczytac. Globalny env (settings.anthropic_api_key itd) jest
    fallbackiem - workspace key ma priorytet.
    """
    with SessionLocal() as session:
        ws = session.get(Workspace, cur.workspace_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Workspace nie istnieje.")
        keys = (ws.api_keys or {}).get("api_keys", {}) if ws.api_keys else {}
        out: list[dict[str, Any]] = []
        for name in WORKSPACE_API_KEY_NAMES:
            ws_value = keys.get(name) or ""
            env_value = os.getenv(name) or ""
            out.append({
                "name": name,
                "workspace_set": bool(ws_value),
                "workspace_masked": _mask_key(ws_value),
                "env_fallback_set": bool(env_value),
                "effective_source": "workspace" if ws_value else ("env" if env_value else "none"),
            })
        return {"keys": out}


class UpdateApiKeysIn(BaseModel):
    """Update API keys. Klucze z wartoscia "" (pusty string) sa usuwane.
    Klucze nieobecne w request - zostaja bez zmian (PATCH semantyka).
    """
    keys: dict[str, str]


@app.put("/api/workspace/api-keys")
def update_workspace_api_keys(
    payload: UpdateApiKeysIn, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Update API keys per workspace. Tylko owner."""
    with SessionLocal() as session:
        ws = session.get(Workspace, cur.workspace_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Workspace nie istnieje.")
        if ws.owner_user_id != cur.user_id and not cur.is_admin:
            raise HTTPException(status_code=403, detail="Tylko owner moze edytowac klucze.")

        api_keys = dict(ws.api_keys or {})
        keys_obj = dict(api_keys.get("api_keys", {}))
        changed: list[str] = []
        for name, value in payload.keys.items():
            if name not in WORKSPACE_API_KEY_NAMES:
                continue  # cicho ignoruj nieznane klucze
            v = (value or "").strip()
            if v == "":
                # Pusty string = usun klucz
                if name in keys_obj:
                    del keys_obj[name]
                    changed.append(f"-{name}")
            else:
                keys_obj[name] = v
                changed.append(f"+{name}")

        api_keys["api_keys"] = keys_obj
        ws.api_keys = api_keys
        if changed:
            session.commit()
            _log_event(cur.workspace_id, cur.user_id, "INFO", "workspace", "api_keys_updated",
                       f"API keys zaktualizowane: {', '.join(changed)}")
    return {"ok": True, "changed": changed}


# ─── Dashboard - filtrowane by workspace ────────────────────────────────

def _start_of_day_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _sparkline_for_ws(workspace_id: int, status: str | None = None, days: int = 12) -> list[int]:
    """Sparkline z `days` ostatnich dni - 1 SQL query z GROUP BY zamiast 12 osobnych.

    Wczesniej: 12 SELECT'ow w petli = 12 round-trip do DB per sparkline.
    Dashboard wola _sparkline_for_ws 3x = 36 query. Teraz: 3 query total.
    """
    from datetime import timedelta
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days - 1)
    date_col = func.date(Lead.created_at).label("day")
    q = select(date_col, func.count(Lead.id)).where(
        Lead.workspace_id == workspace_id,
        Lead.created_at >= start,
        Lead.deleted_at.is_(None),  # ukryj kosz w sparkline
    ).group_by(date_col)
    if status:
        q = q.where(Lead.status == status)
    with SessionLocal() as session:
        rows = session.execute(q).all()
    # Mapa: data -> count
    counts: dict[str, int] = {}
    for day, cnt in rows:
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)
        counts[key] = int(cnt or 0)
    points: list[int] = []
    for i in range(days - 1, -1, -1):
        day_iso = (end - timedelta(days=i)).date().isoformat()
        points.append(counts.get(day_iso, 0))
    return points


def _safe(fn, default, label: str = ""):
    """Wrap a query so a single broken section nigdy nie spali całego dashboardu."""
    try:
        return fn()
    except Exception as exc:
        log.warning(f"dashboard section '{label}' failed: {exc}")
        return default


@app.get("/api/workspace/overview")
def workspace_overview(cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Hala -> Pulpit. Ogólny widok workspace, niezależny od modułu.

    Pokazuje: dane workspace, kredyty, listę modułów (live/soon), agregaty
    pracy w tle (running jobs), ostatnie zdarzenia. Bezpieczne dla pustego
    workspace - każda sekcja ma fallback.
    """
    ws_id = cur.workspace_id

    def _stats():
        with SessionLocal() as session:
            ws = session.get(Workspace, ws_id)
            leads_total = int(session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.workspace_id == ws_id,
                    Lead.deleted_at.is_(None),
                )
            ) or 0)
            drafts_pending = int(session.scalar(
                select(func.count(EmailDraft.id)).where(
                    EmailDraft.workspace_id == ws_id,
                    EmailDraft.status == DraftStatus.DRAFT.value,
                )
            ) or 0)
            running_jobs = int(session.scalar(
                select(func.count(Job.id)).where(
                    Job.workspace_id == ws_id,
                    Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
                )
            ) or 0)
            return {
                "workspace": {
                    "id": ws.id, "name": ws.name, "plan": ws.plan,
                    "credits": ws.monthly_credits, "used_credits": ws.used_credits,
                },
                "leads_total": leads_total,
                "drafts_pending": drafts_pending,
                "running_jobs": running_jobs,
            }

    base = _safe(_stats, {
        "workspace": {"id": ws_id, "name": cur.workspace_name, "plan": cur.workspace_plan,
                      "credits": 0, "used_credits": 0},
        "leads_total": 0, "drafts_pending": 0, "running_jobs": 0,
    }, "overview_stats")

    return {
        **base,
        "modules": [
            {
                "slug": "handlowiec", "name": "Handlowiec",
                "desc": "Cold-email + research leadów + Woodpecker",
                "icon": "robot", "status": "live",
                "href": "/handlowiec/pulpit",
                "metrics": {
                    "leads": base.get("leads_total", 0),
                    "drafts_pending": base.get("drafts_pending", 0),
                },
            },
            {"slug": "kuznia", "name": "Kuźnia Kreatywna",
             "desc": "Wirtualny model, generator reklam, animator packshotów",
             "icon": "anvil", "status": "soon", "href": None},
            {"slug": "kancelaria", "name": "Kancelaria",
             "desc": "Agent Celny, Asystent GPSR",
             "icon": "briefcase", "status": "soon", "href": None},
        ],
        "shortcuts": [
            {"label": "Nowe pozyskiwanie leadów", "href": "/pozyskiwanie", "icon": "search"},
            {"label": "Drafty do review", "href": "/drafty", "icon": "mail-forward"},
            {"label": "Lista leadów", "href": "/leady", "icon": "users"},
        ],
    }


@app.get("/api/dashboard")
def get_dashboard(cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Handlowiec -> Pulpit. Module-specific dashboard cold-mail.

    Każda sekcja w try/except - empty workspace = wszystkie zera, nigdy 500.
    """
    ws_id = cur.workspace_id

    def _counts():
        with SessionLocal() as session:
            # Wszystkie KPI dashboardu wykluczaja leady w koszu - jak user
            # usunie 100 staruszek, dashboard pokazuje rzeczywisty stan.
            def cnt(*conds): return int(session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.workspace_id == ws_id,
                    Lead.deleted_at.is_(None),
                    *conds,
                )
            ) or 0)
            def cnt_d(*conds): return int(session.scalar(
                select(func.count(EmailDraft.id)).where(EmailDraft.workspace_id == ws_id, *conds)
            ) or 0)

            avg_q = session.scalar(
                select(func.avg(Lead.score)).where(
                    Lead.workspace_id == ws_id,
                    Lead.deleted_at.is_(None),
                )
            )

            return {
                "leads_total": cnt(),
                "researched": cnt(Lead.status == LeadStatus.RESEARCHED.value),
                "drafted": cnt(Lead.status == LeadStatus.DRAFTED.value),
                "sent_lead": cnt(Lead.status == LeadStatus.SENT.value),
                "replied": cnt(Lead.status == LeadStatus.REPLIED.value),
                "bounced": cnt(Lead.status == LeadStatus.BOUNCED.value),
                "drafts_pending": cnt_d(EmailDraft.status == DraftStatus.DRAFT.value),
                "sent_today": cnt_d(EmailDraft.status == DraftStatus.SENT.value,
                                    EmailDraft.sent_at >= _start_of_day_utc()),
                "sent_total": cnt_d(EmailDraft.status == DraftStatus.SENT.value),
                "avg_score": float(avg_q) if avg_q is not None else 0.0,
                "hot_leads": cnt(Lead.score >= 7.0),
            }

    c = _safe(_counts, {
        "leads_total": 0, "researched": 0, "drafted": 0, "sent_lead": 0,
        "replied": 0, "bounced": 0, "drafts_pending": 0, "sent_today": 0,
        "sent_total": 0, "avg_score": 0.0, "hot_leads": 0,
    }, "counts")

    def _segments():
        with SessionLocal() as session:
            rows = session.execute(
                select(Lead.segment, func.count(Lead.id))
                .where(
                    Lead.workspace_id == ws_id,
                    Lead.deleted_at.is_(None),
                )
                .group_by(Lead.segment)
                .order_by(func.count(Lead.id).desc())
            ).all()
            return [{"name": (r[0] or "-"), "count": int(r[1])} for r in rows]

    def _running_jobs():
        with SessionLocal() as session:
            return int(session.scalar(
                select(func.count(Job.id)).where(
                    Job.workspace_id == ws_id,
                    Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
                )
            ) or 0)

    segments = _safe(_segments, [], "segments")
    running_jobs = _safe(_running_jobs, 0, "running_jobs")
    sparklines = _safe(
        lambda: {
            "leads": _sparkline_for_ws(ws_id, days=12),
            "drafts": _sparkline_for_ws(ws_id, LeadStatus.DRAFTED.value, 12),
            "replies": _sparkline_for_ws(ws_id, LeadStatus.REPLIED.value, 12),
        },
        {"leads": [0] * 12, "drafts": [0] * 12, "replies": [0] * 12},
        "sparklines",
    )

    leads_total = c["leads_total"]
    sent_total = c["sent_total"]
    drafted_total = c["drafted"] + c["sent_lead"] + c["replied"] + c["bounced"]
    sent_total_w = sent_total + c["replied"] + c["bounced"]
    reply_rate = (c["replied"] / max(sent_total, 1)) * 100 if sent_total else 0.0
    safe_total = max(leads_total, 1)

    # ROI - 'ile agent zaoszczedzil vs reczna praca'.
    # === FILOZOFIA LICZENIA ===
    #
    # Liczymy z BAZY DANYCH (nie z statusow leadow ktore moga sie zmieniac):
    #   - researched = liczba leadow z research_data != NULL
    #     (stabilne - jak user edytuje/odrzuca, research juz byl zrobiony)
    #   - enriched_success = liczba leadow z last_enriched_at != NULL AND email != NULL
    #     (enrich nie zawsze sie udaje - liczymy tylko sukcesy zeby fair)
    #   - drafts_total = liczba EmailDraft (INCLUDING rejected - agent
    #     wlozyl prace, user moze odrzucic ale agent zrobil swoje)
    #   - sent_total = liczba EmailDraft.status='sent'
    #
    # Stawki + czasy AUTOMATYCZNIE pobierane z mapping per rok (poniżej).
    # Co rok aktualizujemy 1 linijke w MIN_WAGE_BY_YEAR i deploy. Bez env,
    # bez konfiguracji uzytkownika.
    rates = _get_roi_rates_for_today()
    min_wage_h = rates["min_wage_h"]
    employer_mult = rates["employer_mult"]
    sales_rate_h = rates["sales_rate_h"]
    min_per_research = rates["min_per_research"]
    min_per_enrich = rates["min_per_enrich"]
    min_per_draft = rates["min_per_draft"]
    min_per_sent = rates["min_per_sent"]

    def _roi_counts():
        """Kanoniczne counts dla ROI - stabilne na przyszlosc bo NIE
        zaleza od bieżących statusów leada (ktore moga byc cofniete).

        Leady w trash SA wliczone do ROI - praca wykonana przez agenta sie
        liczy, nawet jak user pozniej usunal lead (np. zlecił research, lead
        okazał się off-topic, kasuje). Agent nie wie kto będzie usunięty.
        """
        with SessionLocal() as session:
            researched = int(session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.workspace_id == ws_id,
                    Lead.research_data.isnot(None),
                )
            ) or 0)
            enriched_success = int(session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.workspace_id == ws_id,
                    Lead.last_enriched_at.isnot(None),
                    Lead.email.isnot(None),
                    Lead.email != "",
                )
            ) or 0)
            drafts_total = int(session.scalar(
                select(func.count(EmailDraft.id)).where(
                    EmailDraft.workspace_id == ws_id,
                )
            ) or 0)
            sent_drafts = int(session.scalar(
                select(func.count(EmailDraft.id)).where(
                    EmailDraft.workspace_id == ws_id,
                    EmailDraft.status == DraftStatus.SENT.value,
                )
            ) or 0)
            return {
                "researched": researched,
                "enriched_success": enriched_success,
                "drafts_total": drafts_total,
                "sent_drafts": sent_drafts,
            }

    roi_c = _safe(_roi_counts, {
        "researched": 0, "enriched_success": 0,
        "drafts_total": 0, "sent_drafts": 0,
    }, "roi_counts")

    # Minuty per komponent (kazdy moze byc 0 jak nic sie nie wydarzylo)
    min_research = roi_c["researched"] * min_per_research
    min_enrich = roi_c["enriched_success"] * min_per_enrich
    min_drafts = roi_c["drafts_total"] * min_per_draft
    min_sent = roi_c["sent_drafts"] * min_per_sent
    minutes_saved = min_research + min_enrich + min_drafts + min_sent

    hours_saved = round(minutes_saved / 60, 1)

    # 3 stawki:
    #   1. min_wage_brutto - sama placa pracownika (najczestsza referencja)
    #   2. min_wage_employer - REALNY koszt pracodawcy (brutto + ZUS)
    #   3. sales_rate - realistyczna stawka handlowca B2B (najtrafniejsza
    #      bo to wlasnie ten zawod agent zastapuje)
    saved_min_wage_brutto = round((minutes_saved / 60) * min_wage_h, 0)
    saved_min_wage_employer = round((minutes_saved / 60) * min_wage_h * employer_mult, 0)
    saved_sales = round((minutes_saved / 60) * sales_rate_h, 0)

    # Roczna projekcja - dla psychologicznego efektu "ile zaoszczędzisz w skali roku
    # przy obecnym tempie". Liczymy: ile godzin/dzień średnio agent juz pracuje
    # (hours_saved podzielone przez liczbe dni od pierwszego leada do dzis),
    # potem rozszerzamy do 365 dni.
    yearly_saved_pln: dict[str, int] | None = None
    daily_pace_hours: float | None = None
    try:
        with SessionLocal() as session:
            first_lead = session.execute(
                select(func.min(Lead.created_at)).where(Lead.workspace_id == ws_id)
            ).scalar()
        if first_lead is not None and hours_saved > 0:
            if first_lead.tzinfo is None:
                first_lead = first_lead.replace(tzinfo=timezone.utc)
            days_active = max(1.0, (datetime.now(timezone.utc) - first_lead).total_seconds() / 86400)
            daily_pace_hours = hours_saved / days_active
            yearly_hours = daily_pace_hours * 365
            yearly_saved_pln = {
                "min_wage_brutto": int(round(yearly_hours * min_wage_h)),
                "min_wage_employer_cost": int(round(yearly_hours * min_wage_h * employer_mult)),
                "sales_rate": int(round(yearly_hours * sales_rate_h)),
            }
    except Exception as exc:
        log.warning(f"yearly projection failed: {exc}")

    return {
        "workspace": {"id": ws_id, "name": cur.workspace_name, "plan": cur.workspace_plan},
        "stats": {
            "leads_total": leads_total, "leads_hot": c["hot_leads"],
            "drafts_pending": c["drafts_pending"], "avg_score": round(c["avg_score"], 1),
            "researched": c["researched"], "sent_today": c["sent_today"],
            "replied": c["replied"], "reply_rate": round(reply_rate, 1),
            "bounced": c["bounced"], "running_jobs": running_jobs,
        },
        # ROI - "ile agent juz zaoszczedzil" widget na pulpicie.
        # Stawki + czasy automatycznie z mapping per rok (bez env vars).
        # Labelki user-friendly z perspektywy klienta, nie pipeline'u.
        "roi": {
            "hours_saved": hours_saved,
            "minutes_saved": minutes_saved,
            # 3 stawki dla full picture - od konserwatywnej do realistycznej
            "saved_pln": {
                "min_wage_brutto": int(saved_min_wage_brutto),
                "min_wage_employer_cost": int(saved_min_wage_employer),
                "sales_rate": int(saved_sales),
            },
            # Roczna projekcja - "w tym tempie w skali roku zaoszczedzisz X PLN".
            # None gdy brak danych do oszacowania pace'u (workspace pusty / 0 leadow).
            "yearly_saved_pln": yearly_saved_pln,
            "daily_pace_hours": round(daily_pace_hours, 2) if daily_pace_hours else None,
            # Breakdown z perspektywy uzytkownika ("co dokladnie agent robi") -
            # NIE z perspektywy pipeline'u (np. nie pisz "wyciagniecie z google maps"
            # bo user nie obchodzi nasz scraper, ani "filtrowanie" bo to brzmi negatywnie).
            "breakdown": [
                {
                    "label": "Znalezienie firmy z pożądanej branży w internecie",
                    "count": roi_c["researched"],
                    "min_each": min_per_research,
                    "total_min": min_research,
                },
                {
                    "label": "Znalezienie adresu mailowego firmy",
                    "count": roi_c["enriched_success"],
                    "min_each": min_per_enrich,
                    "total_min": min_enrich,
                },
                {
                    "label": "Napisanie spersonalizowanego maila",
                    "count": roi_c["drafts_total"],
                    "min_each": min_per_draft,
                    "total_min": min_drafts,
                },
                {
                    "label": "Wysłanie maila i zapisanie w historii kontaktu",
                    "count": roi_c["sent_drafts"],
                    "min_each": min_per_sent,
                    "total_min": min_sent,
                },
            ],
            # Stawki uzyte (auto-pick z current year). min_wage_pln_per_h
            # to OFICJALNA stawka godzinowa (31.40 dla 2026), NIE wyliczona
            # z miesiecznej - oba sa publikowane w Rozporzadzeniu RM i godzinowa
            # rosnie szybciej niz miesieczna.
            "rates": {
                "year": rates["year"],
                "min_wage_monthly": rates["min_wage_monthly"],
                "min_wage_monthly_net": rates["min_wage_monthly_net"],
                "min_wage_pln_per_h": min_wage_h,
                "min_wage_employer_pln_per_h": round(min_wage_h * employer_mult, 2),
                "employer_cost_multiplier": employer_mult,
                "sales_rate_pln_per_h": sales_rate_h,
            },
        },
        "sparklines": sparklines,
        "funnel": [
            {"label": "Pozyskane", "value": leads_total,
             "percent": 100.0 if leads_total else 0.0, "icon": "upload"},
            {"label": "Researched", "value": c["researched"] + drafted_total,
             "percent": round((c["researched"] + drafted_total) / safe_total * 100, 1), "icon": "search"},
            {"label": "Z draftem", "value": drafted_total,
             "percent": round(drafted_total / safe_total * 100, 1), "icon": "check"},
            {"label": "Wysłane", "value": sent_total_w,
             "percent": round(sent_total_w / safe_total * 100, 1), "icon": "send"},
            {"label": "Odpowiedzieli", "value": c["replied"],
             "percent": round(c["replied"] / safe_total * 100, 1), "icon": "message-circle"},
        ],
        "system": [
            {"label": "Anthropic key", "value": "OK" if os.getenv("ANTHROPIC_API_KEY") else "brak",
             "status": "ok" if os.getenv("ANTHROPIC_API_KEY") else "warn"},
            {"label": "Gemini key", "value": "OK" if os.getenv("GEMINI_API_KEY") else "brak",
             "status": "ok" if os.getenv("GEMINI_API_KEY") else "warn"},
            {"label": "Apify token", "value": "OK" if os.getenv("APIFY_API_TOKEN") else "brak",
             "status": "ok" if os.getenv("APIFY_API_TOKEN") else "warn"},
            {"label": "Google Places", "value": "OK" if os.getenv("GOOGLE_PLACES_API_KEY") else "brak",
             "status": "ok" if os.getenv("GOOGLE_PLACES_API_KEY") else "warn"},
            {"label": "Woodpecker", "value": "OK" if os.getenv("WOODPECKER_API_KEY") else "brak",
             "status": "ok" if os.getenv("WOODPECKER_API_KEY") else "warn"},
        ],
        "segments": segments,
    }


@app.get("/api/events")
def get_events(limit: int = 8, cur: CurrentUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))

    def _icon(src: str, ev_type: str) -> tuple[str, bool]:
        s = (src or "").lower(); t = (ev_type or "").lower()
        if "research" in s or "research" in t: return ("search", True)
        if "discover" in s: return ("upload", True)
        if "generate" in s or "draft" in t: return ("wand", True)
        if "push" in s or "send" in t or "email_sent" in t: return ("send", False)
        if "poll" in s: return ("refresh", False)
        if "auth" in s: return ("key", False)
        if "job" in t: return ("playstation-square", True)
        if "error" in (s + t): return ("x", False)
        return ("circle-dot", False)

    def _time_rel(then: datetime) -> str:
        now = datetime.now(timezone.utc)
        a = now.replace(tzinfo=None) if then.tzinfo is None else now
        b = then.replace(tzinfo=None) if then.tzinfo is None else then
        mins = int((a - b).total_seconds() / 60)
        if mins < 1: return "teraz"
        if mins < 60: return f"{mins}m"
        if mins < 1440: return f"{mins // 60}h"
        return then.strftime("%m-%d")

    import html as _h
    with SessionLocal() as session:
        events = session.execute(
            select(Event)
            .where(Event.workspace_id == cur.workspace_id)
            .order_by(desc(Event.created_at)).limit(limit)
        ).scalars().all()

    out = []
    for e in events:
        ic, acc = _icon(e.source or "", e.type or "")
        msg = e.message or ""
        if len(msg) > 100: msg = msg[:97] + "..."
        out.append({
            "icon": ic, "accent": acc,
            "text": f"<strong>{_h.escape(e.source or '-')}</strong> · {_h.escape(msg)}",
            "time": _time_rel(e.created_at),
        })
    return out


# ─── Leads ───────────────────────────────────────────────────────────────

class LeadCreate(BaseModel):
    """Reczne dodanie leada przez user'a (np. kontakt z targow, polecenia,
    LinkedIn). Omijamy discovery/research - user wpisuje co wie.

    company_name OBLIGATORYJNE - to identifikator. Reszta opcjonalna.
    Jesli user poda email, status = RESEARCHED (gotowy do drafta).
    Jesli nie poda emaila, status = NEW (do enrichmentu).
    """
    company_name: str
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    city: str | None = None
    segment: str | None = None
    notes: str | None = None


@app.post("/api/leads")
def create_lead(
    payload: LeadCreate, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Tworzy lead z reki - bez discovery, bez Apify, bez kredytow.

    Walidacja:
      - company_name required, niepusty
      - segment musi byc w LeadSegment enum (default 'inne')
      - email - prosty regex
      - dedup: jesli website (znormalizowany) juz istnieje w workspace
        i nie jest w koszu -> 409 z pointer'em do istniejacego leada

    Status startowy:
      - RESEARCHED gdy podano email (gotowy do draftowania)
      - NEW gdy bez emaila (do enrichmentu)

    source = 'manual'. Event log 'lead.manually_created'.
    """
    from core.urls import normalize_url

    def _clean(v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s if s else None

    company_name = _clean(payload.company_name)
    if not company_name:
        raise HTTPException(status_code=422, detail="Nazwa firmy jest wymagana.")
    if len(company_name) > 255:
        raise HTTPException(status_code=422, detail="Nazwa firmy max 255 znakow.")

    segment = _clean(payload.segment) or LeadSegment.INNE.value
    valid_segments = {s.value for s in LeadSegment}
    if segment not in valid_segments:
        raise HTTPException(
            status_code=422,
            detail=f"Nieprawidlowy segment. Dozwolone: {sorted(valid_segments)}",
        )

    email = _clean(payload.email)
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=422, detail="Nieprawidlowy format email.")

    website_raw = _clean(payload.website)
    website_norm = normalize_url(website_raw) if website_raw else ""

    with SessionLocal() as session:
        # Dedup po website (znormalizowanym) - jesli ten sam adres juz w bazie
        # i nie w koszu -> 409 zamiast cicho tworzyc duplikat.
        if website_norm:
            existing = session.execute(
                select(Lead).where(
                    Lead.workspace_id == cur.workspace_id,
                    Lead.deleted_at.is_(None),
                )
            ).scalars().all()
            for ex in existing:
                if normalize_url(ex.website) == website_norm:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": (
                                f"Lead o tym adresie www juz istnieje: "
                                f"#{ex.id} {ex.company_name}."
                            ),
                            "existing_lead_id": ex.id,
                        },
                    )

        status_value = (
            LeadStatus.RESEARCHED.value if email else LeadStatus.NEW.value
        )
        lead = Lead(
            workspace_id=cur.workspace_id,
            segment=segment,
            company_name=company_name,
            contact_name=_clean(payload.contact_name),
            email=email,
            phone=_clean(payload.phone),
            website=website_raw,
            city=_clean(payload.city),
            country="PL",
            source="manual",
            status=status_value,
            notes=_clean(payload.notes),
        )
        session.add(lead)
        session.flush()  # zeby miec lead.id w event log

        session.add(Event(
            workspace_id=cur.workspace_id,
            user_id=cur.user_id,
            lead_id=lead.id,
            type="lead.manually_created",
            level="INFO",
            source="user",
            message=(
                f"User recznie dodal lead: {lead.company_name} "
                f"(segment={segment}, email={'tak' if email else 'brak'})"
            ),
            payload={
                "company_name": lead.company_name,
                "segment": segment,
                "has_email": bool(email),
                "has_website": bool(website_raw),
            },
        ))
        session.commit()
        session.refresh(lead)

        return {
            "ok": True,
            "lead": {
                "id": lead.id,
                "company_name": lead.company_name,
                "contact_name": lead.contact_name,
                "email": lead.email,
                "phone": lead.phone,
                "website": lead.website,
                "city": lead.city,
                "segment": lead.segment,
                "status": lead.status,
                "source": lead.source,
                "notes": lead.notes,
            },
        }


@app.get("/api/leads")
def list_leads(
    limit: int = 50, offset: int = 0,
    segment: str | None = None, status: str | None = None, min_score: float = 0.0,
    q: str | None = None,
    sort: str = "newest",  # default najnowsze - swieze leady na gorze
    cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Lista leadow + agregowane statystyki draftow per lead.

    Parametry:
      q       - full-text search po company_name LUB email (case-insensitive ILIKE)
      sort    - 'score' (default: score DESC, puste na dol) | 'newest' | 'oldest' | 'company'
      segment/status/min_score - filtry
    """
    limit = max(1, min(limit, 200)); offset = max(0, offset)
    with SessionLocal() as session:
        empty_email = (Lead.email.is_(None)) | (Lead.email == "")
        empty_phone = (Lead.phone.is_(None)) | (Lead.phone == "")
        empty_flag = case(
            (Lead.status == LeadStatus.DEAD_END.value, 2),
            ((empty_email & empty_phone), 1),
            else_=0,
        )
        base = select(Lead).where(
            Lead.workspace_id == cur.workspace_id,
            Lead.deleted_at.is_(None),  # ukryj kosz
        )
        if segment: base = base.where(Lead.segment == segment)
        if status: base = base.where(Lead.status == status)
        if min_score > 0: base = base.where(Lead.score >= min_score)
        if q and q.strip():
            search = f"%{q.strip()}%"
            base = base.where(
                (Lead.company_name.ilike(search))
                | (Lead.email.ilike(search))
                | (Lead.contact_name.ilike(search))
            )

        if sort == "newest":
            ordered = base.order_by(empty_flag.asc(), desc(Lead.created_at))
        elif sort == "oldest":
            ordered = base.order_by(empty_flag.asc(), Lead.created_at.asc())
        elif sort == "company":
            ordered = base.order_by(empty_flag.asc(), Lead.company_name.asc())
        else:  # 'score' default
            ordered = base.order_by(empty_flag.asc(), desc(Lead.score), desc(Lead.created_at))

        total = int(session.scalar(select(func.count()).select_from(ordered.subquery())) or 0)
        rows = session.execute(ordered.limit(limit).offset(offset)).scalars().all()

        # Agregat: ile draftow per lead + status najnowszego (do kolumny w tabeli).
        # Pojedyncze query zamiast N+1: GROUP BY lead_id wszystkie drafty workspace'u
        # i mapujemy ID -> {count, latest_status} (limit do leadow z bieżącej strony).
        lead_ids = [l.id for l in rows]
        drafts_info: dict[int, dict[str, Any]] = {}
        if lead_ids:
            # ile draftow per lead
            counts_rows = session.execute(
                select(EmailDraft.lead_id, func.count(EmailDraft.id))
                .where(
                    EmailDraft.lead_id.in_(lead_ids),
                    EmailDraft.workspace_id == cur.workspace_id,
                )
                .group_by(EmailDraft.lead_id)
            ).all()
            for lid, cnt in counts_rows:
                drafts_info.setdefault(lid, {})["count"] = int(cnt)
            # status najnowszego draftu per lead (subquery z DISTINCT ON byloby
            # ladniejsze ale dla SQLite nie dziala - lecimy fetch + grouping in-app)
            latest_rows = session.execute(
                select(EmailDraft.lead_id, EmailDraft.status, EmailDraft.id)
                .where(
                    EmailDraft.lead_id.in_(lead_ids),
                    EmailDraft.workspace_id == cur.workspace_id,
                )
                .order_by(EmailDraft.lead_id, desc(EmailDraft.id))
            ).all()
            seen_lids: set[int] = set()
            for lid, st, _did in latest_rows:
                if lid in seen_lids:
                    continue
                seen_lids.add(lid)
                drafts_info.setdefault(lid, {})["latest_status"] = st

        # Active job per lead - mapowanie lead_id -> typ joba (gen_draft / enrich)
        # zeby UI pokazal indykator "praca w toku" obok wiersza w tabeli.
        active_job_by_lead: dict[int, str] = {}
        if lead_ids:
            with SessionLocal() as session2:
                running_jobs = session2.execute(
                    select(Job).where(
                        Job.workspace_id == cur.workspace_id,
                        Job.status.in_(["pending", "running"]),
                        Job.type.in_([
                            "generate_draft", "enrich_lead", "research_lead",
                        ]),
                    )
                    .order_by(desc(Job.created_at))
                    .limit(50)
                ).scalars().all()
                lead_id_set = set(lead_ids)
                for j in running_jobs:
                    if not isinstance(j.payload, dict):
                        continue
                    lid = j.payload.get("lead_id")
                    if isinstance(lid, int) and lid in lead_id_set:
                        # Pierwszy job winsuje (najnowszy bo ORDER BY desc created_at)
                        if lid not in active_job_by_lead:
                            active_job_by_lead[lid] = j.type

        leads = [{
            "id": l.id, "segment": l.segment, "company_name": l.company_name,
            "contact_name": l.contact_name, "email": l.email, "phone": l.phone,
            "website": l.website, "city": l.city, "status": l.status,
            "score": float(l.score) if l.score is not None else None,
            "created_at": iso_utc(l.created_at),
            "drafts_count": drafts_info.get(l.id, {}).get("count", 0),
            "latest_draft_status": drafts_info.get(l.id, {}).get("latest_status"),
            # 'generate_draft' | 'enrich_lead' | 'research_lead' | None
            # UI pokaze pulsujaca kropke + tooltip 'Pracuje nad ...'
            "active_job_type": active_job_by_lead.get(l.id),
        } for l in rows]
    return {"total": total, "items": leads}


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Lead detail z draftami i timeline eventow.

    Drafty: lista wszystkich draftow tego leada (zeby drawer mogl pokazac
    historie + aktualny active draft do klikniecia "Otworz w Drafty").
    Events: timeline aktywnosci per-lead (uzywa Event.lead_id z migracji 0002).
    Active jobs: lista RUNNING/PENDING jobow ktore dotycza tego leada (np.
    generate_draft odpalony z drawera) zeby UI pokazywal "Pracuje..."
    bez native alert'a.
    """
    with SessionLocal() as session:
        # Detail dostepny tez dla leadow w trash (user moze klikac z /leady/trash).
        # Filtruje deleted_at jedynie listing /api/leads (lista glowna).
        lead = session.execute(
            select(Lead).where(Lead.id == lead_id, Lead.workspace_id == cur.workspace_id)
        ).scalar_one_or_none()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead nie istnieje.")

        drafts = session.execute(
            select(EmailDraft)
            .where(
                EmailDraft.lead_id == lead_id,
                EmailDraft.workspace_id == cur.workspace_id,
            )
            .order_by(desc(EmailDraft.created_at))
        ).scalars().all()

        events = session.execute(
            select(Event)
            .where(
                Event.lead_id == lead_id,
                Event.workspace_id == cur.workspace_id,
            )
            .order_by(desc(Event.created_at))
            .limit(50)
        ).scalars().all()

        # Aktywne jobs - filter po payload (lead_id jest w payload JSON).
        # Dla skali w przyszlosci dodac Job.lead_id kolumne, na razie szukamy
        # ostatnich 20 jobow workspace'u w pamiec.
        recent_jobs = session.execute(
            select(Job)
            .where(
                Job.workspace_id == cur.workspace_id,
                Job.status.in_(["pending", "running"]),
            )
            .order_by(desc(Job.created_at)).limit(20)
        ).scalars().all()
        active_jobs_for_lead = [
            {
                "id": j.id, "type": j.type, "status": j.status,
                "progress": j.progress, "total": j.total,
                "created_at": iso_utc(j.created_at),
            }
            for j in recent_jobs
            if isinstance(j.payload, dict) and j.payload.get("lead_id") == lead_id
        ]

        return {
            "id": lead.id, "segment": lead.segment,
            "company_name": lead.company_name, "contact_name": lead.contact_name,
            "email": lead.email, "phone": lead.phone, "website": lead.website,
            "instagram": lead.instagram, "city": lead.city, "country": lead.country,
            "status": lead.status,
            "score": float(lead.score) if lead.score is not None else None,
            "research_data": lead.research_data, "notes": lead.notes,
            "created_at": iso_utc(lead.created_at),
            "updated_at": iso_utc(lead.updated_at),
            "drafts": [
                {
                    "id": d.id,
                    "subject": d.subject,
                    "status": d.status,
                    "template_variant": d.template_variant,
                    "edited_by_user": d.edited_by_user,
                    "created_at": iso_utc(d.created_at),
                    "sent_at": iso_utc(d.sent_at),
                }
                for d in drafts
            ],
            "events": [
                {
                    "id": e.id,
                    "type": e.type,
                    "level": e.level,
                    "source": e.source,
                    "message": e.message,
                    "created_at": iso_utc(e.created_at),
                }
                for e in events
            ],
            "active_jobs": active_jobs_for_lead,
        }


# ─── Drafts ──────────────────────────────────────────────────────────────

class LeadUpdate(BaseModel):
    """Reczna edycja leada przez user'a w drawer'ze.

    Tylko pola ktore user moze sensownie poprawic. NIE company_name (to
    identyfikator) ani score (to LLM assessment) ani research_data
    (to history of LLM call).

    Wszystkie optional - PATCH semantyka, tylko podane pola updatowane.
    """
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    city: str | None = None
    segment: str | None = None
    notes: str | None = None


@app.patch("/api/leads/{lead_id}")
def update_lead(
    lead_id: int, payload: LeadUpdate,
    cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Manualna edycja leada. Pozwala uzytkownikowi poprawic email/telefon/
    kontakt itp. ktorych agent nie znalazl albo wyciagnal zle.

    Side-effects:
    - Po dodaniu emaila do leada ze status=DEAD_END -> status cofany do
      RESEARCHED (jak w enrich endpoint - lead odblokowuje sie do draftowania).
    - Update Lead.updated_at (auto przez SQLAlchemy onupdate).
    - Event log "lead.manually_edited" z lead_id + lista zmienionych pol.
    """
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="Nic do zaktualizowania.")

    # Walidacja segmentu - musi byc znana wartosc
    if "segment" in update_data and update_data["segment"]:
        valid_segments = {s.value for s in LeadSegment}
        if update_data["segment"] not in valid_segments:
            raise HTTPException(
                status_code=422,
                detail=f"Nieprawidlowy segment. Dozwolone: {sorted(valid_segments)}",
            )

    # Walidacja emaila - prosty regex jak dla bezpieczenstwa
    if "email" in update_data and update_data["email"]:
        email = update_data["email"].strip()
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise HTTPException(status_code=422, detail="Nieprawidlowy format email.")
        update_data["email"] = email or None

    with SessionLocal() as session:
        lead = session.execute(
            select(Lead).where(
                Lead.id == lead_id, Lead.workspace_id == cur.workspace_id,
                Lead.deleted_at.is_(None),  # nie edytuj leadow w koszu - musi byc restore
            )
        ).scalar_one_or_none()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead nie istnieje (lub w koszu).")

        # Normalizuj puste stringi do None (zgodnie z _clean() w save_lead)
        for k, v in list(update_data.items()):
            if isinstance(v, str):
                s = v.strip()
                update_data[k] = s if s else None

        changed_fields: list[str] = []
        for field, value in update_data.items():
            old = getattr(lead, field, None)
            if old != value:
                setattr(lead, field, value)
                changed_fields.append(field)

        # Side-effect: dodanie emaila do DEAD_END leada -> cofnij na RESEARCHED
        if (
            "email" in update_data and update_data["email"]
            and lead.status == LeadStatus.DEAD_END.value
        ):
            lead.status = LeadStatus.RESEARCHED.value
            changed_fields.append("status (auto: dead_end -> researched)")

        if changed_fields:
            session.add(Event(
                workspace_id=cur.workspace_id,
                user_id=cur.user_id,
                lead_id=lead.id,
                type="lead.manually_edited",
                level="INFO",
                source="user",
                message=f"User zedytowal recznie: {', '.join(changed_fields)}",
                payload={"fields": changed_fields},
            ))
        session.commit()
        session.refresh(lead)

        return {
            "ok": True,
            "changed_fields": changed_fields,
            "lead": {
                "id": lead.id, "segment": lead.segment,
                "company_name": lead.company_name,
                "contact_name": lead.contact_name,
                "email": lead.email, "phone": lead.phone,
                "website": lead.website, "city": lead.city,
                "status": lead.status, "notes": lead.notes,
            },
        }


# ─── Kosz (soft-delete + 7-day auto-purge) ────────────────────────────────
#
# User usuwa lead -> deleted_at = utcnow() (soft-delete). Lead znika z list
# i dashboardu ale zostaje w DB przez RECYCLE_BIN_DAYS dni. Worker tick auto-purge
# co 1h hard-deletuje stare wpisy z trash (drafty cascade).
#
# User moze:
#   - restore z trash (deleted_at -> None, status zachowany)
#   - permanent delete (hard delete + cascade)
#   - empty trash (hard delete wszystkie w trash workspace'u)
#   - bulk delete (lista lead_ids -> wszystkie do trash)

RECYCLE_BIN_DAYS = int(os.getenv("RECYCLE_BIN_DAYS") or 7)


@app.delete("/api/leads/{lead_id}")
def delete_lead(
    lead_id: int, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Soft-delete: lead trafia do kosza (deleted_at = now()). Hard delete dopiero
    przez /api/leads/{id}/permanent albo automatyczny worker auto-purge po
    RECYCLE_BIN_DAYS dniach (default 7).

    Drafty zostaja - mozemy je obejrzec gdy lead jest w trash, restore przywroci
    je z powrotem.
    """
    with SessionLocal() as session:
        lead = session.execute(
            select(Lead).where(
                Lead.id == lead_id, Lead.workspace_id == cur.workspace_id,
                Lead.deleted_at.is_(None),  # nie mozna soft-delete drugi raz
            )
        ).scalar_one_or_none()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead nie istnieje (lub juz w koszu).")

        company = lead.company_name
        lead.deleted_at = datetime.now(timezone.utc)
        session.add(Event(
            workspace_id=cur.workspace_id,
            user_id=cur.user_id,
            lead_id=lead.id,
            type="lead.moved_to_trash",
            level="INFO",
            source="user",
            message=f"Lead #{lead_id} ({company}) przeniesiony do kosza",
            payload={
                "lead_id": lead_id, "company": company,
                "auto_purge_in_days": RECYCLE_BIN_DAYS,
            },
        ))
        session.commit()
        return {
            "ok": True, "lead_id": lead_id, "company": company,
            "auto_purge_in_days": RECYCLE_BIN_DAYS,
        }


class BulkDeleteIn(BaseModel):
    lead_ids: list[int]


@app.post("/api/leads/bulk-delete")
def bulk_delete_leads(
    payload: BulkDeleteIn, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Bulk soft-delete (z bulk-bar w /leady - przycisk 'Usun (N)').

    Filtruje: tylko leady ktore naleza do workspace i nie sa juz w koszu.
    Skip'uje cicho reszte. Max 100 naraz (ochrona przed bulk-misclick).
    """
    if not payload.lead_ids:
        raise HTTPException(status_code=400, detail="Brak lead_ids.")
    if len(payload.lead_ids) > 100:
        raise HTTPException(status_code=400, detail="Max 100 leadow naraz.")

    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        eligible = session.execute(
            select(Lead).where(
                Lead.id.in_(payload.lead_ids),
                Lead.workspace_id == cur.workspace_id,
                Lead.deleted_at.is_(None),
            )
        ).scalars().all()
        deleted_ids: list[int] = []
        for lead in eligible:
            lead.deleted_at = now
            deleted_ids.append(lead.id)
        if deleted_ids:
            session.add(Event(
                workspace_id=cur.workspace_id,
                user_id=cur.user_id,
                type="lead.bulk_moved_to_trash",
                level="INFO",
                source="user",
                message=f"User przeniosl {len(deleted_ids)} leadow do kosza",
                payload={"lead_ids": deleted_ids, "auto_purge_in_days": RECYCLE_BIN_DAYS},
            ))
        session.commit()
    return {
        "ok": True,
        "requested": len(payload.lead_ids),
        "moved_to_trash": len(deleted_ids),
        "skipped": len(payload.lead_ids) - len(deleted_ids),
        "auto_purge_in_days": RECYCLE_BIN_DAYS,
    }


@app.post("/api/leads/{lead_id}/restore")
def restore_lead(
    lead_id: int, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Przywroc lead z kosza: deleted_at = None, status zachowany."""
    with SessionLocal() as session:
        lead = session.execute(
            select(Lead).where(
                Lead.id == lead_id, Lead.workspace_id == cur.workspace_id,
                Lead.deleted_at.is_not(None),
            )
        ).scalar_one_or_none()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead nie jest w koszu.")
        lead.deleted_at = None
        session.add(Event(
            workspace_id=cur.workspace_id,
            user_id=cur.user_id,
            lead_id=lead.id,
            type="lead.restored",
            level="INFO",
            source="user",
            message=f"Lead #{lead_id} ({lead.company_name}) przywrocony z kosza",
            payload={"lead_id": lead_id, "company": lead.company_name},
        ))
        session.commit()
        return {"ok": True, "lead_id": lead_id, "company": lead.company_name}


@app.delete("/api/leads/{lead_id}/permanent")
def permanent_delete_lead(
    lead_id: int, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Hard delete - tylko leady JUZ w koszu. Cascade na drafty.

    Eventy lead_id zostaja jako null (FK on lead.id, brak ondelete cascade
    w schemacie - w przyszlosci dorzucic).
    """
    with SessionLocal() as session:
        lead = session.execute(
            select(Lead).where(
                Lead.id == lead_id, Lead.workspace_id == cur.workspace_id,
                Lead.deleted_at.is_not(None),
            )
        ).scalar_one_or_none()
        if lead is None:
            raise HTTPException(
                status_code=404,
                detail="Lead nie jest w koszu. Przenies do kosza (DELETE /api/leads/{id}) najpierw.",
            )

        company = lead.company_name
        session.add(Event(
            workspace_id=cur.workspace_id,
            user_id=cur.user_id,
            type="lead.permanently_deleted",
            level="WARNING",
            source="user",
            message=f"User usunal PERMANENTNIE lead #{lead_id} ({company})",
            payload={"deleted_lead_id": lead_id, "company": company},
        ))
        session.delete(lead)  # cascade -> drafty
        session.commit()
        return {"ok": True, "deleted_lead_id": lead_id, "company": company}


@app.get("/api/leads/trash")
def list_trash(
    limit: int = 100, offset: int = 0,
    cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Lista leadow w koszu (deleted_at IS NOT NULL), ordered by deleted_at DESC.

    Kazdy wiersz zawiera 'days_until_purge' - frontend pokazuje countdown
    "auto-usuniecie za X dni".
    """
    limit = max(1, min(limit, 500)); offset = max(0, offset)
    now = datetime.now(timezone.utc)
    cutoff_days = RECYCLE_BIN_DAYS
    with SessionLocal() as session:
        base = select(Lead).where(
            Lead.workspace_id == cur.workspace_id,
            Lead.deleted_at.is_not(None),
        ).order_by(desc(Lead.deleted_at))
        total = int(session.scalar(
            select(func.count()).select_from(base.subquery())
        ) or 0)
        rows = session.execute(base.limit(limit).offset(offset)).scalars().all()

        items = []
        for l in rows:
            del_at = l.deleted_at
            if del_at is not None and del_at.tzinfo is None:
                del_at = del_at.replace(tzinfo=timezone.utc)
            days_since_delete = (now - del_at).total_seconds() / 86400 if del_at else 0
            days_until_purge = max(0, cutoff_days - days_since_delete)
            items.append({
                "id": l.id, "segment": l.segment,
                "company_name": l.company_name,
                "contact_name": l.contact_name,
                "email": l.email, "phone": l.phone, "website": l.website,
                "city": l.city, "status": l.status,
                "score": float(l.score) if l.score is not None else None,
                "deleted_at": iso_utc(l.deleted_at),
                "days_until_purge": round(days_until_purge, 1),
                "created_at": iso_utc(l.created_at),
            })
    return {
        "total": total,
        "items": items,
        "recycle_bin_days": cutoff_days,
    }


@app.post("/api/leads/trash/empty")
def empty_trash(cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Hard delete wszystkich leadow w koszu workspace'u. Cascade na drafty."""
    with SessionLocal() as session:
        trash = session.execute(
            select(Lead).where(
                Lead.workspace_id == cur.workspace_id,
                Lead.deleted_at.is_not(None),
            )
        ).scalars().all()
        deleted_count = len(trash)
        deleted_ids = [l.id for l in trash]
        for lead in trash:
            session.delete(lead)  # cascade -> drafty
        if deleted_count:
            session.add(Event(
                workspace_id=cur.workspace_id,
                user_id=cur.user_id,
                type="trash.emptied",
                level="WARNING",
                source="user",
                message=f"User wyczyscil kosz: {deleted_count} leadow usunietych permanentnie",
                payload={"deleted_count": deleted_count, "lead_ids": deleted_ids},
            ))
        session.commit()
    return {"ok": True, "deleted_count": deleted_count}


@app.get("/api/drafts")
def list_drafts(
    status_filter: str | None = "draft", limit: int = 50,
    cur: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Lista draftow + KONTEKST leada (kontakt, email, segment, miasto, score)
    + status wysylki do Woodpeckera (pending job / ostatni error).

    status_filter: "draft" | "approved" | "sent" | "rejected" | "all" (lub None).
    """
    limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        q = select(EmailDraft).options(joinedload(EmailDraft.lead)) \
            .where(EmailDraft.workspace_id == cur.workspace_id) \
            .order_by(desc(EmailDraft.created_at)).limit(limit)
        if status_filter and status_filter != "all":
            q = q.where(EmailDraft.status == status_filter)
        drafts = session.execute(q).unique().scalars().all()
        draft_ids = [d.id for d in drafts]

        # Status SEND_DRAFT jobow dla tych draftow - kolejka i ostatni blad.
        # Worker triggeruje push_draft() ktore moze sie wywalic (DRY_RUN, brak
        # WOODPECKER_API_KEY, lead bez emaila, STOP.txt). Pokazujemy to userowi.
        last_send_error: dict[int, str] = {}
        send_in_progress: set[int] = set()
        if draft_ids:
            send_jobs = session.execute(
                select(Job).where(
                    Job.workspace_id == cur.workspace_id,
                    Job.type == JobType.SEND_DRAFT.value,
                ).order_by(desc(Job.created_at)).limit(500)
            ).scalars().all()
            for j in send_jobs:
                did = j.payload.get("draft_id") if isinstance(j.payload, dict) else None
                if not isinstance(did, int) or did not in draft_ids:
                    continue
                if j.status in (JobStatus.PENDING.value, JobStatus.RUNNING.value):
                    send_in_progress.add(did)
                elif j.status == JobStatus.FAILED.value and did not in last_send_error:
                    last_send_error[did] = j.last_error or "Wysylka sie nie powiodla."

        return [{
            "id": d.id, "lead_id": d.lead_id,
            "company": d.lead.company_name if d.lead else "(unknown)",
            # KONTEKST leada do header'a maila w UI:
            "lead_contact_name": d.lead.contact_name if d.lead else None,
            "lead_email": d.lead.email if d.lead else None,
            "lead_segment": d.lead.segment if d.lead else None,
            "lead_city": d.lead.city if d.lead else None,
            "lead_score": float(d.lead.score) if d.lead and d.lead.score is not None else None,
            # Sama tresc maila:
            "subject": d.subject, "snippet1": d.snippet1, "snippet2": d.snippet2,
            "snippet3": d.snippet3, "snippet5": d.snippet5,
            "full_preview": d.full_preview, "status": d.status,
            "template_variant": d.template_variant, "edited_by_user": d.edited_by_user,
            "generated_by_model": d.generated_by_model,
            "created_at": iso_utc(d.created_at),
            "sent_at": iso_utc(d.sent_at),
            # Sygnaly wysylki - kluczowe by user widzial co sie dzieje:
            "woodpecker_prospect_id": d.woodpecker_prospect_id,
            "send_in_progress": d.id in send_in_progress,
            "last_send_error": last_send_error.get(d.id),
        } for d in drafts]


class DraftUpdate(BaseModel):
    subject: str | None = None
    snippet1: str | None = None
    snippet2: str | None = None
    snippet3: str | None = None
    snippet5: str | None = None


@app.patch("/api/drafts/{draft_id}")
def update_draft(draft_id: int, payload: DraftUpdate,
                 cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    from agent.generate import _strip_ai_artifacts
    with SessionLocal() as session:
        draft = session.execute(
            select(EmailDraft).where(
                EmailDraft.id == draft_id, EmailDraft.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft nie istnieje.")
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            if value is None: continue
            setattr(draft, field, _strip_ai_artifacts(value) or value)
        parts = [f"Subject: {draft.subject}", "", draft.snippet1 or "", "",
                 draft.snippet2 or "", "", draft.snippet3 or ""]
        parts.extend(["", draft.snippet5 or ""])
        draft.full_preview = "\n".join(parts)
        draft.edited_by_user = True
        session.commit()
        _log_event(cur.workspace_id, cur.user_id, "INFO", "gui", "draft_edited",
                   f"Draft #{draft_id} edited")
        return {"ok": True, "draft_id": draft_id}


@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: int, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    with SessionLocal() as session:
        draft = session.execute(
            select(EmailDraft).where(
                EmailDraft.id == draft_id, EmailDraft.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if draft is None: raise HTTPException(status_code=404, detail="Draft nie istnieje.")
        draft.status = DraftStatus.APPROVED.value
        # Lead status: drafted -> approved (sygnalizuje "gotowy do wyslania")
        lead = session.get(Lead, draft.lead_id)
        if lead is not None and lead.status in (LeadStatus.DRAFTED.value, LeadStatus.RESEARCHED.value):
            lead.status = LeadStatus.APPROVED.value
        session.commit()
        _log_event(cur.workspace_id, cur.user_id, "INFO", "gui", "draft_approved",
                   f"Draft #{draft_id} approved")
        return {"ok": True}


@app.post("/api/drafts/{draft_id}/reject")
def reject_draft(draft_id: int, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Odrzuc draft + cofnij lead.status do RESEARCHED jesli nie ma juz innych
    non-rejected draftow (bug fix: lead zostawal w 'drafted' mimo ze wszystkie
    drafty byly odrzucone -> blokowal generowanie nowego)."""
    with SessionLocal() as session:
        draft = session.execute(
            select(EmailDraft).where(
                EmailDraft.id == draft_id, EmailDraft.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if draft is None: raise HTTPException(status_code=404, detail="Draft nie istnieje.")
        lead_id = draft.lead_id
        draft.status = DraftStatus.REJECTED.value
        session.flush()

        # Czy lead ma JESZCZE jakikolwiek non-rejected draft?
        active_count = int(session.scalar(
            select(func.count(EmailDraft.id)).where(
                EmailDraft.lead_id == lead_id,
                EmailDraft.workspace_id == cur.workspace_id,
                EmailDraft.status != DraftStatus.REJECTED.value,
            )
        ) or 0)

        if active_count == 0:
            # Brak aktywnych draftow - lead wraca do "researched" (gotowy do
            # nowej generacji). NIE ruszamy stanow finalnych (SENT/REPLIED/BOUNCED)
            # bo to historyczne stany ktorych nie cofamy.
            lead = session.get(Lead, lead_id)
            if lead is not None and lead.status in (
                LeadStatus.DRAFTED.value, LeadStatus.APPROVED.value,
            ):
                lead.status = LeadStatus.RESEARCHED.value
                log.info(f"Lead #{lead_id} status cofniety do 'researched' (wszystkie drafty rejected)")

        session.commit()
        _log_event(cur.workspace_id, cur.user_id, "INFO", "gui", "draft_rejected",
                   f"Draft #{draft_id} rejected")
        return {"ok": True, "lead_id": lead_id, "active_drafts": active_count}


class SendDraftIn(BaseModel):
    campaign_id: int


class BulkSendDraftsIn(BaseModel):
    draft_ids: list[int]
    campaign_id: int


@app.post("/api/drafts/bulk-send")
def bulk_send_drafts(
    payload: BulkSendDraftsIn, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Bulk push wielu draftow do Woodpeckera. Tworzy N osobnych SEND_DRAFT
    jobow (worker przetwarza pojedynczo z rate-limitem 1.2s do Woodpeckera).

    Filtruje:
      - status musi byc 'draft' albo 'approved'
      - lead musi miec email
      - draft musi miec subject (twarda walidacja w push_draft i tak by zablokowala)
      - nie wysylamy ponownie tego co juz SENT
      - nie kolejkujemy drugi raz draftu ktory ma aktywny SEND_DRAFT job
    Skipowane wracaja jako lista {draft_id, reason} - user widzi czemu cos
    nie poszlo, ale operacja sie nie blokuje na pojedynczym blędzie.
    """
    if not payload.draft_ids:
        raise HTTPException(status_code=400, detail="Brak draft_ids.")
    if len(payload.draft_ids) > 50:
        raise HTTPException(status_code=400, detail="Max 50 draftow naraz.")

    with SessionLocal() as session:
        drafts = session.execute(
            select(EmailDraft).options(joinedload(EmailDraft.lead)).where(
                EmailDraft.id.in_(payload.draft_ids),
                EmailDraft.workspace_id == cur.workspace_id,
            )
        ).unique().scalars().all()

        found_ids = {d.id for d in drafts}
        missing_ids = set(payload.draft_ids) - found_ids

        # Drafty z aktywnym SEND_DRAFT jobem - zeby nie kolejkowac drugi raz.
        active_send_jobs = session.execute(
            select(Job).where(
                Job.workspace_id == cur.workspace_id,
                Job.type == JobType.SEND_DRAFT.value,
                Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
            )
        ).scalars().all()
        active_draft_ids: set[int] = set()
        for j in active_send_jobs:
            did = j.payload.get("draft_id") if isinstance(j.payload, dict) else None
            if isinstance(did, int):
                active_draft_ids.add(did)

        skipped: list[dict[str, Any]] = []
        for mid in missing_ids:
            skipped.append({"draft_id": mid, "reason": "nie istnieje w tym workspace"})

        job_ids: list[int] = []
        queued_draft_ids: list[int] = []
        for d in drafts:
            if d.status == DraftStatus.SENT.value:
                skipped.append({"draft_id": d.id, "reason": "juz wyslany"})
                continue
            if d.status == DraftStatus.REJECTED.value:
                skipped.append({"draft_id": d.id, "reason": "odrzucony"})
                continue
            if d.id in active_draft_ids:
                skipped.append({"draft_id": d.id, "reason": "wysylka juz w kolejce"})
                continue
            if not (d.subject or "").strip():
                skipped.append({"draft_id": d.id, "reason": "pusty temat - wygeneruj ponownie"})
                continue
            if not d.lead or not (d.lead.email or "").strip():
                skipped.append({"draft_id": d.id, "reason": "lead bez emaila"})
                continue

            job = create_job(
                session, job_type=JobType.SEND_DRAFT,
                workspace_id=cur.workspace_id, user_id=cur.user_id,
                payload={"draft_id": d.id, "campaign_id": payload.campaign_id},
            )
            job_ids.append(job.id)
            queued_draft_ids.append(d.id)

    return {
        "ok": True,
        "requested": len(payload.draft_ids),
        "queued": len(job_ids),
        "skipped": skipped,
        "queued_draft_ids": queued_draft_ids,
        "job_ids": job_ids,
    }


@app.post("/api/drafts/{draft_id}/send")
def send_draft(draft_id: int, payload: SendDraftIn,
               cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Tworzy SEND_DRAFT job - worker pushuje do Woodpecker, user może wyjść.

    Blokuje re-send: jesli draft juz SENT lub jest aktywny SEND_DRAFT job
    w kolejce - zwraca 409 zeby user nie zaspamowal tej samej osoby."""
    with SessionLocal() as session:
        draft = session.execute(
            select(EmailDraft).where(
                EmailDraft.id == draft_id, EmailDraft.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if draft is None: raise HTTPException(status_code=404, detail="Draft nie istnieje.")
        if draft.status == DraftStatus.SENT.value:
            raise HTTPException(
                status_code=409,
                detail=("Draft juz wyslany do Woodpecker"
                        f"{' ' + iso_utc(draft.sent_at) if draft.sent_at else ''}. "
                        "Nie wysylamy tej samej wiadomosci drugi raz - "
                        "uzyj follow-upu jesli chcesz wrocic do tego leada."),
            )
        if draft.status == DraftStatus.REJECTED.value:
            raise HTTPException(
                status_code=409,
                detail="Draft odrzucony - przywroc go (lub wygeneruj nowy) zanim wyslesz.",
            )

        active_send_job = session.execute(
            select(Job).where(
                Job.workspace_id == cur.workspace_id,
                Job.type == JobType.SEND_DRAFT.value,
                Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
            )
        ).scalars().all()
        for j in active_send_job:
            if isinstance(j.payload, dict) and j.payload.get("draft_id") == draft_id:
                raise HTTPException(
                    status_code=409,
                    detail=f"Wysylka tego draftu jest juz w kolejce (job #{j.id}).",
                )

        job = create_job(
            session, job_type=JobType.SEND_DRAFT,
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            payload={"draft_id": draft_id, "campaign_id": payload.campaign_id},
        )
    return {"ok": True, "job_id": job.id}


class RegenerateSnippetIn(BaseModel):
    snippet_name: str
    instruction: str | None = None


@app.post("/api/drafts/{draft_id}/regenerate")
def regenerate_snippet(draft_id: int, payload: RegenerateSnippetIn,
                       cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Regeneracja per-snippet - synchronicznie bo jest szybkie (1-2s)."""
    from agent.generate import regenerate_snippet as _regen
    with SessionLocal() as session:
        draft = session.execute(
            select(EmailDraft).where(
                EmailDraft.id == draft_id, EmailDraft.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if draft is None: raise HTTPException(status_code=404, detail="Draft nie istnieje.")
    try:
        new_text = _regen(draft_id, payload.snippet_name,
                          user_instruction=payload.instruction)
        return {"ok": True, "text": new_text}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class CreateDraftIn(BaseModel):
    lead_id: int
    provider: str | None = None
    model: str | None = None


@app.post("/api/drafts")
def create_draft(payload: CreateDraftIn, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Tworzy GENERATE_DRAFT job."""
    with SessionLocal() as session:
        # Sprawdź czy lead należy do workspace i nie jest w koszu
        lead = session.execute(
            select(Lead).where(
                Lead.id == payload.lead_id,
                Lead.workspace_id == cur.workspace_id,
                Lead.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if lead is None: raise HTTPException(status_code=404, detail="Lead nie istnieje w Twoim workspace (lub w koszu).")
        job = create_job(
            session, job_type=JobType.GENERATE_DRAFT,
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            payload={
                "lead_id": payload.lead_id,
                "provider": payload.provider, "model": payload.model,
            },
        )
    return {"ok": True, "job_id": job.id}


class BulkDraftsIn(BaseModel):
    lead_ids: list[int]
    provider: str | None = None
    model: str | None = None


@app.post("/api/drafts/bulk")
def create_drafts_bulk(
    payload: BulkDraftsIn, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Bulk-generate: tworzy GENERATE_DRAFT job per lead_id (a nie jeden BULK
    job) - daje per-lead retry + widzialny progress per lead w UI.

    Filtruje: tylko leady ktore naleza do workspace, maja status RESEARCHED
    i nie maja juz aktywnego (non-rejected) draftu. Skip'uje cicho reszte.
    """
    if not payload.lead_ids:
        raise HTTPException(status_code=400, detail="Brak lead_ids.")
    if len(payload.lead_ids) > 50:
        raise HTTPException(status_code=400, detail="Max 50 leadow naraz.")

    with SessionLocal() as session:
        # Wczytaj leady ktore matchuja workspace + sa researched + nie maja
        # aktywnego draftu (LEFT JOIN by counted by non-rejected drafts)
        eligible = session.execute(
            select(Lead).where(
                Lead.id.in_(payload.lead_ids),
                Lead.workspace_id == cur.workspace_id,
                Lead.status == LeadStatus.RESEARCHED.value,
                Lead.email.isnot(None),
                Lead.email != "",
                Lead.deleted_at.is_(None),  # nie draftuj leadow z kosza
            )
        ).scalars().all()

        # Sprawdz ktore juz maja non-rejected draft
        existing_drafts_lead_ids = set(session.execute(
            select(EmailDraft.lead_id).where(
                EmailDraft.lead_id.in_([l.id for l in eligible]),
                EmailDraft.workspace_id == cur.workspace_id,
                EmailDraft.status != DraftStatus.REJECTED.value,
            )
        ).scalars().all())

        to_queue = [l for l in eligible if l.id not in existing_drafts_lead_ids]
        job_ids: list[int] = []
        for lead in to_queue:
            job = create_job(
                session, job_type=JobType.GENERATE_DRAFT,
                workspace_id=cur.workspace_id, user_id=cur.user_id,
                payload={
                    "lead_id": lead.id,
                    "provider": payload.provider, "model": payload.model,
                },
            )
            job_ids.append(job.id)

    return {
        "ok": True,
        "requested": len(payload.lead_ids),
        "queued": len(job_ids),
        "skipped_not_researched": len(payload.lead_ids) - len(eligible),
        "skipped_already_has_draft": len(eligible) - len(to_queue),
        "job_ids": job_ids,
    }


# ─── Discovery + research jako jobs ─────────────────────────────────────

# Globalny dzienny cap per workspace (free plan). W przyszlosci per-plan.
DISCOVERY_DAILY_CAP_FREE = int(os.getenv("DISCOVERY_DAILY_CAP_FREE") or 1000)


class DiscoverIn(BaseModel):
    query: str
    sources: list[str]
    max_per_source: int = 50
    segment: str = "inne"
    location: str | None = None
    custom_description: str | None = None
    use_relevance_filter: bool = True
    relevance_threshold: int = 6
    auto_research: bool = True
    auto_draft_threshold: int | None = 7
    # Per-source query override. Klucz = source key (np. "apify_allegro").
    # Pozwala wyslac Google Places po "sklep plastyczny Krakow" a w tym samym
    # requescie Apify Allegro po "preset:sklep_plastyczny". Brak override =
    # source dostaje glowny `query`.
    source_queries: dict[str, str] | None = None
    # Skip-if-recent: jak ten sam (segment, location, sources) zostal odpalony
    # w ostatnich CACHE_TTL_DAYS - serwujemy z bazy zamiast palac kredytu.
    # force_refresh=True omija cache - drogi, ale czasem chcesz odswiezyc.
    force_refresh: bool = False
    # Query expansion: zamiast jednego query "sklep papierniczy Warszawa" wyslij
    # serie wariantow (synonimy + dzielnice) zeby ominac limit 60/query. Kazdy
    # wariant ma osobny cache key. Default OFF bo drogi (do 30 calli per peek).
    expand_queries: bool = False
    # Max wariantow przy expand_queries=True. Cap zeby user nie spalil budzetu.
    expand_max_variants: int = 30


def _discovery_today_count(workspace_id: int) -> int:
    """Ile leadów workspace pozyskał już dziś (cap dzienny).

    Liczy WSZYSTKIE pozyskane dzis, NAWET trash - user nie obchodzi limit
    Apify/LLM (token spalony to spalony, nawet jak lead potem do kosza).
    """
    with SessionLocal() as session:
        return int(session.scalar(
            select(func.count(Lead.id)).where(
                Lead.workspace_id == workspace_id,
                Lead.created_at >= _start_of_day_utc(),
            )
        ) or 0)


@app.get("/api/discovery/industry-presets")
def list_industry_presets(cur: CurrentUser = Depends(get_current_user)) -> list[dict[str, str]]:
    """Lista presetow branz dla query mode 'preset' (Allegro discovery).
    Frontend uzywa do dropdownu."""
    from core.industry_presets import list_segments_with_presets
    _ = cur  # auth check
    return list_segments_with_presets()


@app.get("/api/discovery/cities")
def list_cities_pl(
    voivodeship: str | None = None,
    top_n: int | None = None,
    cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Lista miast PL z knowledge base. Frontend uzywa do smart city picker.

    Filtry:
      voivodeship - tylko z danego wojewodztwa
      top_n - tylko top N po populacji (np. ?top_n=30)
    """
    from core.cities_pl import CITIES_PL, VOIVODESHIPS, cities_in_voivodeship, get_top_cities
    _ = cur
    if voivodeship:
        cities = cities_in_voivodeship(voivodeship)
    elif top_n:
        cities = get_top_cities(top_n)
    else:
        cities = CITIES_PL
    return {
        "cities": cities,
        "voivodeships": VOIVODESHIPS,
        "total": len(CITIES_PL),
    }


# ── Discovery Exclusions (per-workspace blacklist) ─────────────────────

class DiscoveryExclusionIn(BaseModel):
    exclusion_type: str  # 'domain' | 'brand' | 'city_segment'
    value: str
    reason: str | None = None


@app.get("/api/discovery/exclusions")
def list_exclusions(cur: CurrentUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Lista exclusions per workspace - co nie ma sensu skanowac."""
    with SessionLocal() as session:
        rows = session.execute(
            select(DiscoveryExclusion).where(
                DiscoveryExclusion.workspace_id == cur.workspace_id,
            ).order_by(DiscoveryExclusion.created_at.desc())
        ).scalars().all()
        return [{
            "id": r.id, "exclusion_type": r.exclusion_type,
            "value": r.value, "reason": r.reason,
            "created_at": iso_utc(r.created_at),
        } for r in rows]


@app.post("/api/discovery/exclusions")
def add_exclusion(
    payload: DiscoveryExclusionIn,
    cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Dodaj wykluczenie. Idempotent - jak juz istnieje, zwraca 200 OK
    z istniejacym id."""
    valid_types = {"domain", "brand", "city_segment"}
    if payload.exclusion_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Nieprawidlowy typ. Dozwolone: {sorted(valid_types)}",
        )
    value = (payload.value or "").strip().lower()
    if not value:
        raise HTTPException(status_code=422, detail="Wartosc nie moze byc pusta.")

    with SessionLocal() as session:
        existing = session.execute(
            select(DiscoveryExclusion).where(
                DiscoveryExclusion.workspace_id == cur.workspace_id,
                DiscoveryExclusion.exclusion_type == payload.exclusion_type,
                DiscoveryExclusion.value == value,
            ).limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            return {"ok": True, "id": existing.id, "created": False}
        excl = DiscoveryExclusion(
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            exclusion_type=payload.exclusion_type,
            value=value, reason=(payload.reason or "").strip() or None,
        )
        session.add(excl)
        session.commit()
        session.refresh(excl)
        return {"ok": True, "id": excl.id, "created": True}


@app.delete("/api/discovery/exclusions/{exclusion_id}")
def delete_exclusion(
    exclusion_id: int, cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    with SessionLocal() as session:
        excl = session.execute(
            select(DiscoveryExclusion).where(
                DiscoveryExclusion.id == exclusion_id,
                DiscoveryExclusion.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if excl is None:
            raise HTTPException(status_code=404, detail="Nie ma takiego wykluczenia.")
        session.delete(excl)
        session.commit()
    return {"ok": True}


# Cache TTL dla discovery runow - po tym czasie ten sam (segment, location,
# sources) wywoluje API od nowa. 30 dni = balance miedzy ratowaniem kredytu
# a swiezoscia danych (firmy umieraja/powstaja powoli).
DISCOVERY_CACHE_TTL_DAYS = int(os.getenv("DISCOVERY_CACHE_TTL_DAYS") or 30)


def _discovery_query_hash(
    segment: str, location: str | None, sources: list[str],
    custom_description: str | None,
) -> str:
    """Stabilny hash query do cache lookup.

    Bierze: segment + location + sorted sources + custom_description.
    Stable across requests - identyczny query daje identyczny hash niezaleznie
    od kolejnosci elementow w sources liscie.
    """
    import hashlib
    key = "|".join([
        (segment or "").strip().lower(),
        (location or "").strip().lower(),
        ",".join(sorted(s.strip().lower() for s in sources or [])),
        (custom_description or "").strip().lower(),
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _find_cached_discovery(
    session: Session, workspace_id: int, query_hash: str,
) -> DiscoveryRun | None:
    """Zwraca najswiezszy DiscoveryRun dla danego query_hash w workspace,
    jezeli jest mlodszy niz CACHE_TTL i ma cached_places. Inaczej None.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=DISCOVERY_CACHE_TTL_DAYS)
    return session.execute(
        select(DiscoveryRun).where(
            DiscoveryRun.workspace_id == workspace_id,
            DiscoveryRun.query_hash == query_hash,
            DiscoveryRun.run_at >= cutoff,
            DiscoveryRun.cached_places.isnot(None),
        ).order_by(DiscoveryRun.run_at.desc()).limit(1)
    ).scalar_one_or_none()


def _filter_excluded(places: list, workspace_id: int) -> list:
    """Wyrzuca places ktore matchuja domain/brand z DiscoveryExclusion.

    Match logika:
      - 'domain': znormalizowana domena z place.website zawiera wartosc
      - 'brand': nazwa firmy (place.name) zawiera wartosc (case insensitive)

    Zwraca tylko te ktore PRZESZLY filter (NIE wykluczone).
    Tania query - jedno SELECT exclusions per workspace.
    """
    from core.urls import normalize_url

    if not places:
        return places
    with SessionLocal() as session:
        exclusions = session.execute(
            select(DiscoveryExclusion).where(
                DiscoveryExclusion.workspace_id == workspace_id,
                DiscoveryExclusion.exclusion_type.in_(["domain", "brand"]),
            )
        ).scalars().all()
    if not exclusions:
        return places

    excluded_domains = {
        e.value.lower() for e in exclusions if e.exclusion_type == "domain"
    }
    excluded_brands = {
        e.value.lower() for e in exclusions if e.exclusion_type == "brand"
    }

    kept = []
    for p in places:
        # Domain match (substring w znormalizowanej domenie)
        if excluded_domains:
            domain = normalize_url(p.website or "").lower()
            if any(d in domain for d in excluded_domains):
                continue
        # Brand match (nazwa zawiera value)
        if excluded_brands:
            name_lower = (p.name or "").lower()
            if any(b in name_lower for b in excluded_brands):
                continue
        kept.append(p)
    return kept


def _run_expanded_discovery(
    payload: "DiscoverIn",
    cur: "CurrentUser",
    sources_objs: list,
) -> dict[str, Any]:
    """Faza 1.5 - Query Expansion: omija limit 60 wynikow per API.

    Dla (segment, location) generuje N wariacji (synonimy + dzielnice),
    kazda variantka leci osobnym run_search + ma swoj cache key. Wyniki
    dedupowane po normalize_url(website) - 5-8x wiecej unikalnych firm
    niz pojedyncze query.

    Cache dziala per variant - druga ta sama variantka w 30 dni = 0 kredytu.

    Paralelizm: ThreadPoolExecutor(max_workers=5) bo Apify/Places maja
    rate limits. Timeout per variant 60s.
    """
    from concurrent.futures import ThreadPoolExecutor
    from core.query_expansion import expand_query
    from core.urls import normalize_url
    from agent.discovery import (
        DiscoveredPlace, mark_existing_in_db, run_search, score_relevance_batch,
        _heuristic_score,
    )

    variants = expand_query(
        payload.segment, payload.location,
        max_variants=payload.expand_max_variants,
    )
    if not variants:
        # Fallback: no expansion possible (np. preset bez synonimow), zwroc
        # pusto - caller (discovery_peek) zlapie i pojdzie standardowa drogo
        return {"_no_expansion": True}

    log.info(
        f"discovery expand: {len(variants)} wariantow dla "
        f"segment={payload.segment!r} location={payload.location!r}"
    )

    stats = {"cache_hits": 0, "api_calls": 0, "errors": 0}

    def _process_variant(query: str, location: str | None) -> list[DiscoveredPlace]:
        """Pojedyncza variantka: cache check -> run_search -> cache write."""
        v_hash = _discovery_query_hash(
            payload.segment, location, payload.sources,
            payload.custom_description,
        )
        # Cache lookup per variant
        if not payload.force_refresh:
            with SessionLocal() as session:
                cached = _find_cached_discovery(session, cur.workspace_id, v_hash)
                if cached is not None:
                    stats["cache_hits"] += 1
                    try:
                        return [
                            DiscoveredPlace(**p)
                            for p in (cached.cached_places or [])
                        ]
                    except Exception:
                        return []
        # Cache miss - fire API
        try:
            places, _diag = run_search(
                sources_objs,
                query=query,
                max_results_per_source=payload.max_per_source,
                workspace_id=cur.workspace_id,
                source_queries=payload.source_queries,
            )
            stats["api_calls"] += 1
            # Cache write
            try:
                with SessionLocal() as session:
                    session.add(DiscoveryRun(
                        workspace_id=cur.workspace_id, user_id=cur.user_id,
                        query_hash=v_hash, segment=payload.segment,
                        location=location, sources=payload.sources,
                        query=query, custom_description=payload.custom_description,
                        cached_places=[p.model_dump() for p in places],
                        result_count=len(places),
                    ))
                    session.commit()
            except Exception:
                pass  # cache write best-effort
            return places
        except Exception as exc:
            log.warning(f"expand variant failed for query={query!r}: {exc}")
            stats["errors"] += 1
            return []

    # Wykonaj wszystkie wariacje paralelnie
    all_places: list[DiscoveredPlace] = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(_process_variant, q, loc)
            for q, loc in variants
        ]
        for future in futures:
            try:
                all_places.extend(future.result(timeout=60))
            except Exception:
                stats["errors"] += 1

    # Dedup po normalize_url(website) - tylko unique firmy
    seen: dict[str, DiscoveredPlace] = {}
    for p in all_places:
        key = normalize_url(p.website or "") or f"{p.source}:{p.raw_id or p.name}"
        if key in seen:
            existing = seen[key]
            if not existing.website and p.website:
                seen[key] = p
            elif (p.review_count or 0) > (existing.review_count or 0):
                seen[key] = p
        else:
            seen[key] = p
    deduped = list(seen.values())

    # Mark istniejace leady (existing_lead_id) zeby user wiedzial co duplikat
    mark_existing_in_db(deduped, workspace_id=cur.workspace_id)

    # Filter exclusions - znormalizowana domena lub brand match
    deduped = _filter_excluded(deduped, cur.workspace_id)

    # LLM relevance scoring na mergowanej liscie
    rel_map: dict[int, dict[str, Any]] = {}
    relevance_source = "none"
    if payload.use_relevance_filter and deduped:
        try:
            items, _ = score_relevance_batch(
                deduped, segment=payload.segment,
                city=payload.location,
                custom_description=payload.custom_description,
            )
            for it in items:
                if 0 <= it.idx < len(deduped):
                    rel_map[it.idx] = {"score": it.score, "reason": it.reason}
            relevance_source = "llm"
        except Exception as exc:
            log.warning(f"expand: relevance batch failed, falling back: {exc}")
            for i, p in enumerate(deduped):
                if p.existing_lead_id is not None:
                    score_int = (
                        int(round(p.existing_lead_score))
                        if p.existing_lead_score is not None else 5
                    )
                    rel_map[i] = {
                        "score": max(0, min(10, score_int)),
                        "reason": f"Duplikat - juz w bazie jako lead #{p.existing_lead_id}",
                    }
                else:
                    score, reason = _heuristic_score(p)
                    rel_map[i] = {"score": score, "reason": reason}
            relevance_source = "heuristic"

    return {
        "places": [{
            "source": p.source, "name": p.name, "website": p.website,
            "address": p.address, "phone": p.phone, "email": p.email,
            "rating": p.rating, "review_count": p.review_count,
            "existing_lead_id": p.existing_lead_id,
            "existing_lead_score": p.existing_lead_score,
            "relevance": rel_map.get(i),
        } for i, p in enumerate(deduped)],
        "diagnostics": [{
            "source": "expanded",
            "places": [],
            "duration_s": 0,
            "note": (
                f"Expansion: {len(variants)} wariantow, "
                f"{stats['cache_hits']} cache hit, "
                f"{stats['api_calls']} API call, "
                f"{stats['errors']} error, "
                f"{len(all_places)} przed dedupem, "
                f"{len(deduped)} po dedupie"
            ),
        }],
        "relevance_source": relevance_source,
        "from_cache": False,
        "expand_stats": {
            "variants_total": len(variants),
            "cache_hits": stats["cache_hits"],
            "api_calls": stats["api_calls"],
            "errors": stats["errors"],
            "places_before_dedup": len(all_places),
            "places_after_dedup": len(deduped),
        },
    }


@app.post("/api/discovery/peek")
def discovery_peek(payload: DiscoverIn, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Praca ręczna: SYNC discovery + relevance scoring, BEZ researchu i draftów.

    User dostaje listę kandydatów z trafnością LLM i sam wybiera których
    chce researchować. Nie pali tokenów na research dopóki user nie kliknie.

    Czas odpowiedzi: 5-30s (Apify call + ewentualnie LLM batch scoring).
    """
    from agent.discovery import (
        ApifyAllegroSource, ApifyLinkedInSource, ApifySource,
        GooglePlacesSource, run_search, score_relevance_batch,
    )

    payload.max_per_source = max(1, min(payload.max_per_source, 100))
    today_done = _discovery_today_count(cur.workspace_id)
    if today_done >= DISCOVERY_DAILY_CAP_FREE:
        raise HTTPException(
            status_code=429,
            detail=f"Dzienny limit pozyskiwania ({DISCOVERY_DAILY_CAP_FREE} leadów) "
                   f"wyczerpany. Spróbuj jutro.",
        )

    # Cache check - pomijamy Apify/Places call jak ten sam query byl w
    # ostatnich CACHE_TTL_DAYS dni. Force refresh omija.
    query_hash = _discovery_query_hash(
        payload.segment, payload.location, payload.sources,
        payload.custom_description,
    )
    cached_run: DiscoveryRun | None = None
    if not payload.force_refresh:
        with SessionLocal() as session:
            cached_run = _find_cached_discovery(session, cur.workspace_id, query_hash)
    if cached_run is not None:
        # Serve from cache - mark places z aktualnymi existing_lead_id
        # (lead'y w bazie mogly sie pojawic/zniknac od cached run).
        from agent.discovery import DiscoveredPlace, mark_existing_in_db
        try:
            cached_places = [
                DiscoveredPlace(**p) for p in (cached_run.cached_places or [])
            ]
        except Exception:
            cached_places = []
        if cached_places:
            mark_existing_in_db(cached_places, workspace_id=cur.workspace_id)
        rel_map_cached: dict[int, dict[str, Any]] = {}
        # Zwracamy bez LLM relevance (cache nie trzyma reason'ow per place)
        # - frontend pokazuje placeholder lub heurystyke
        from agent.discovery import _heuristic_score
        for i, p in enumerate(cached_places):
            if p.existing_lead_id is not None:
                score_int = (
                    int(round(p.existing_lead_score))
                    if p.existing_lead_score is not None else 5
                )
                rel_map_cached[i] = {
                    "score": max(0, min(10, score_int)),
                    "reason": f"Duplikat - już w bazie jako lead #{p.existing_lead_id}",
                }
            else:
                score, reason = _heuristic_score(p)
                rel_map_cached[i] = {"score": score, "reason": reason}
        return {
            "places": [{
                "source": p.source, "name": p.name, "website": p.website,
                "address": p.address, "phone": p.phone, "email": p.email,
                "rating": p.rating, "review_count": p.review_count,
                "existing_lead_id": p.existing_lead_id,
                "existing_lead_score": p.existing_lead_score,
                "relevance": rel_map_cached.get(i),
            } for i, p in enumerate(cached_places)],
            "diagnostics": [{
                "source": "cache",
                "places": cached_run.cached_places or [],
                "duration_s": 0,
            }],
            "daily_used": today_done,
            "daily_cap": DISCOVERY_DAILY_CAP_FREE,
            "relevance_source": "cache",
            "from_cache": True,
            "cached_at": iso_utc(cached_run.run_at),
            "cached_run_id": cached_run.id,
        }

    src_classes = {
        "apify": ApifySource, "google_places": GooglePlacesSource,
        "apify_allegro": ApifyAllegroSource, "apify_linkedin": ApifyLinkedInSource,
    }
    sources = []
    for s in payload.sources:
        cls = src_classes.get(s)
        if cls is None: continue
        inst = cls()
        if inst.available():
            sources.append(inst)
    if not sources:
        raise HTTPException(
            status_code=400,
            detail="Żadne źródło nie jest skonfigurowane (brak kluczy API).",
        )

    # Faza 1.5: Query Expansion - omija limit 60/query przez wariacje
    # (synonimy + dzielnice). Per variant osobny cache key. Paralelnie.
    if payload.expand_queries:
        expanded = _run_expanded_discovery(payload, cur, sources)
        if not expanded.get("_no_expansion"):
            # Add daily counter info ktore expand sam nie wraca
            expanded["daily_used"] = today_done
            expanded["daily_cap"] = DISCOVERY_DAILY_CAP_FREE
            return expanded
        # Else: no variants generated, fall through to standard single-query flow

    try:
        places, diag = run_search(
            sources, query=payload.query,
            max_results_per_source=payload.max_per_source,
            workspace_id=cur.workspace_id,
            source_queries=payload.source_queries,
        )
    except Exception as exc:
        log.exception(f"discovery_peek run_search failed: {exc}")
        # Zapisz audit log nawet dla błędu
        with SessionLocal() as session:
            session.add(DiscoveryRun(
                workspace_id=cur.workspace_id, user_id=cur.user_id,
                query_hash=query_hash, segment=payload.segment,
                location=payload.location, sources=payload.sources,
                query=payload.query, custom_description=payload.custom_description,
                result_count=0, cached_places=None,
                error=str(exc)[:1000],
            ))
            session.commit()
        raise HTTPException(status_code=502, detail=f"Błąd źródeł: {exc}")

    # Apply user-defined exclusions (domain/brand) przed LLM scoring
    places = _filter_excluded(places, cur.workspace_id)

    rel_map: dict[int, dict[str, Any]] = {}
    relevance_source = "none"  # "llm" | "heuristic" | "none"
    if payload.use_relevance_filter and places:
        try:
            items, _ = score_relevance_batch(
                places, segment=payload.segment,
                city=payload.location,
                custom_description=payload.custom_description,
            )
            for it in items:
                if 0 <= it.idx < len(places):
                    rel_map[it.idx] = {"score": it.score, "reason": it.reason}
            relevance_source = "llm"
        except Exception as exc:
            log.warning(f"score_relevance_batch failed (fallback to heuristic): {exc}")
            # Fallback: heurystyka per place (keyword'y w nazwie). NIE LLM,
            # ale lepsze niz puste null ktore powoduje 0-zaznaczonych w UI.
            from agent.discovery import _heuristic_score
            for i, p in enumerate(places):
                if p.existing_lead_id is not None:
                    # Duplikat - poznaczamy zachowanym score'em
                    score_int = (
                        int(round(p.existing_lead_score))
                        if p.existing_lead_score is not None else 5
                    )
                    rel_map[i] = {
                        "score": max(0, min(10, score_int)),
                        "reason": f"Duplikat - już w bazie jako lead #{p.existing_lead_id}",
                    }
                else:
                    score, reason = _heuristic_score(p)
                    rel_map[i] = {"score": score, "reason": reason}
            relevance_source = "heuristic"

    # Zapisz audit log + cache snapshot wynikow zeby ten sam query w
    # ciagu DISCOVERY_CACHE_TTL_DAYS nie palil kredytu ponownie.
    try:
        cached_places_snapshot = [p.model_dump() for p in places]
        with SessionLocal() as session:
            session.add(DiscoveryRun(
                workspace_id=cur.workspace_id, user_id=cur.user_id,
                query_hash=query_hash, segment=payload.segment,
                location=payload.location, sources=payload.sources,
                query=payload.query, custom_description=payload.custom_description,
                cached_places=cached_places_snapshot,
                result_count=len(places),
            ))
            session.commit()
    except Exception as exc:
        log.warning(f"Failed to write DiscoveryRun cache snapshot: {exc}")

    return {
        "places": [{
            "source": p.source, "name": p.name, "website": p.website,
            "address": p.address, "phone": p.phone, "email": p.email,
            "rating": p.rating, "review_count": p.review_count,
            "existing_lead_id": p.existing_lead_id,
            "existing_lead_score": p.existing_lead_score,
            "relevance": rel_map.get(i),
        } for i, p in enumerate(places)],
        "diagnostics": [d.model_dump() for d in diag],
        "daily_used": today_done,
        "daily_cap": DISCOVERY_DAILY_CAP_FREE,
        # Flaga dla frontu - czy relevance pochodzi z LLM czy fallback
        "relevance_source": relevance_source,
        "from_cache": False,
    }


@app.get("/api/discovery/history")
def discovery_history(
    limit: int = 50, cur: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Lista ostatnich discovery runow workspace - dla "Historia" panelu.

    Pokazuje co user juz sprawdzal, kiedy, ile firm wrocilo i czy
    skonczylo sie błędem. Klik wiersza pozwala wrocic do wynikow
    (jeszcze nie zaimplementowane - tylko log audit na teraz).
    """
    limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        runs = session.execute(
            select(DiscoveryRun).where(
                DiscoveryRun.workspace_id == cur.workspace_id,
            ).order_by(DiscoveryRun.run_at.desc()).limit(limit)
        ).scalars().all()
        cutoff = datetime.now(timezone.utc) - timedelta(days=DISCOVERY_CACHE_TTL_DAYS)
        return [{
            "id": r.id,
            "segment": r.segment,
            "location": r.location,
            "sources": r.sources or [],
            "query": r.query,
            "result_count": r.result_count,
            "leads_added": r.leads_added,
            "cost_usd": r.cost_usd,
            "error": r.error,
            "run_at": iso_utc(r.run_at),
            # True jezeli ten run jest jeszcze w okresie cache - znaczy ze
            # kolejne zapytanie z tym samym query_hash nie zapłaci za API.
            "cache_active": r.run_at >= cutoff and r.cached_places is not None,
        } for r in runs]


@app.post("/api/discovery/search")
def discovery_search(payload: DiscoverIn, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Wyślij agenta w teren: tworzy DISCOVERY_PIPELINE job.

    Worker robi pełen pipeline: znajdź -> filter -> research -> draft.
    Zwraca job_id natychmiast. Frontend polluje /api/jobs/{id} dla progressu.
    User może wylogować się - worker leci dalej.

    Twardy cap: DISCOVERY_DAILY_CAP_FREE leadów / dzień / workspace żeby nie
    spalić budżetu Apify / LLM. W przyszłości per-plan limits.
    """
    payload.max_per_source = max(1, min(payload.max_per_source, 100))
    today_done = _discovery_today_count(cur.workspace_id)
    if today_done >= DISCOVERY_DAILY_CAP_FREE:
        raise HTTPException(
            status_code=429,
            detail=f"Dzienny limit pozyskiwania ({DISCOVERY_DAILY_CAP_FREE} leadów) "
                   f"wyczerpany. Spróbuj jutro.",
        )
    with SessionLocal() as session:
        active_count = count_active_jobs(
            session, cur.workspace_id,
            job_types=[JobType.DISCOVERY_PIPELINE.value, JobType.BULK_RESEARCH_LEADS.value],
        )
        if active_count >= MAX_CONCURRENT_HEAVY_JOBS:
            active = find_active_job(
                session, cur.workspace_id,
                job_types=[JobType.DISCOVERY_PIPELINE.value, JobType.BULK_RESEARCH_LEADS.value],
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "msg": f"Kolejka pełna ({active_count}/{MAX_CONCURRENT_HEAVY_JOBS} jobów). "
                           f"Worker robi po kolei - poczekaj aż skończy obecne, albo anuluj któryś.",
                    "active_job_id": active.id if active else None,
                    "active_jobs_count": active_count,
                    "max_concurrent": MAX_CONCURRENT_HEAVY_JOBS,
                },
            )
        job = create_job(
            session, job_type=JobType.DISCOVERY_PIPELINE,
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            payload=payload.model_dump(),
        )
    return {"ok": True, "job_id": job.id, "queue_position": active_count + 1,
            "daily_used": today_done, "daily_cap": DISCOVERY_DAILY_CAP_FREE}


class ResearchIn(BaseModel):
    url: str
    segment_hint: str | None = None
    city_hint: str | None = None
    force_refresh: bool = False


@app.post("/api/research")
def research_lead(payload: ResearchIn, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Single-lead research as job."""
    with SessionLocal() as session:
        job = create_job(
            session, job_type=JobType.RESEARCH_LEAD,
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            payload=payload.model_dump(),
        )
    return {"ok": True, "job_id": job.id}


class BulkResearchIn(BaseModel):
    urls: list[str]
    segment_hint: str | None = None
    city_hint: str | None = None
    auto_draft_threshold: int | None = None
    # User zaznaczyl duplikat w pozyskiwaniu -> chce re-research mimo ze
    # lead juz w bazie. Spala tokeny LLM ponownie, ale aktualizuje
    # research_data + score. Default False (zachowaj stare zachowanie).
    force_refresh: bool = False


@app.post("/api/research/bulk")
def bulk_research(payload: BulkResearchIn, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Praca ręczna: bulk research z listy URLi (po wybraniu z /api/discovery/peek).

    Tworzy jeden BULK_RESEARCH_LEADS job - worker przelatuje listę. Progress
    via /api/jobs/{id}.
    """
    urls = [u.strip() for u in payload.urls if u and u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="Pusta lista URLi.")
    if len(urls) > DISCOVERY_DAILY_CAP_FREE:
        raise HTTPException(
            status_code=400,
            detail=f"Za dużo URLi w jednej partii (max {DISCOVERY_DAILY_CAP_FREE}).",
        )
    with SessionLocal() as session:
        active_count = count_active_jobs(
            session, cur.workspace_id,
            job_types=[JobType.DISCOVERY_PIPELINE.value, JobType.BULK_RESEARCH_LEADS.value],
        )
        if active_count >= MAX_CONCURRENT_HEAVY_JOBS:
            active = find_active_job(
                session, cur.workspace_id,
                job_types=[JobType.DISCOVERY_PIPELINE.value, JobType.BULK_RESEARCH_LEADS.value],
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "msg": f"Kolejka pełna ({active_count}/{MAX_CONCURRENT_HEAVY_JOBS} jobów). "
                           f"Worker robi po kolei - poczekaj aż skończy, albo anuluj któryś.",
                    "active_job_id": active.id if active else None,
                    "active_jobs_count": active_count,
                    "max_concurrent": MAX_CONCURRENT_HEAVY_JOBS,
                },
            )
        job = create_job(
            session, job_type=JobType.BULK_RESEARCH_LEADS,
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            payload={
                "urls": urls,
                "segment_hint": payload.segment_hint,
                "city_hint": payload.city_hint,
                "auto_draft_threshold": payload.auto_draft_threshold,
                "force_refresh": payload.force_refresh,
            },
        )
    return {"ok": True, "job_id": job.id, "total": len(urls)}


# ─── Enrichment ──────────────────────────────────────────────────────────

class EnrichOneIn(BaseModel):
    lead_id: int


@app.post("/api/leads/enrich")
def enrich_one(payload: EnrichOneIn, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Enrich pojedynczego leada (regex po homepage + /kontakt). Tani fallback
    jezeli LLM research nie wyciagnal email/phone. Bez kosztu LLM."""
    with SessionLocal() as session:
        lead = session.execute(
            select(Lead).where(
                Lead.id == payload.lead_id,
                Lead.workspace_id == cur.workspace_id,
                Lead.deleted_at.is_(None),  # nie enrichuj leadow w koszu
            )
        ).scalar_one_or_none()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead nie istnieje (lub w koszu).")
        job = create_job(
            session, job_type=JobType.ENRICH_LEAD,
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            payload={"lead_id": payload.lead_id},
        )
    return {"ok": True, "job_id": job.id}


class EnrichEmptyIn(BaseModel):
    limit: int = 100
    include_dead_end: bool = False


@app.post("/api/leads/enrich-empty")
def enrich_empty(payload: EnrichEmptyIn, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Batch enrichment - przeleci wszystkie leady ws bez email+phone, scrape
    homepage + /kontakt, dorzuci kontakty albo oznaczy DEAD_END.

    Pominie leady oznaczone juz DEAD_END (chyba ze include_dead_end=True),
    pominie tez te enrichowane w ostatnich 90 dniach (RECHECK_DAYS w contact_finder).
    """
    from agent.contact_finder import find_leads_to_enrich
    candidates = find_leads_to_enrich(
        cur.workspace_id,
        limit=max(1, min(payload.limit, 1000)),
        include_dead_end=payload.include_dead_end,
    )
    if not candidates:
        return {"ok": True, "job_id": None, "candidates": 0, "msg": "Brak leadow do enrichmentu."}
    with SessionLocal() as session:
        job = create_job(
            session, job_type=JobType.BULK_ENRICH_LEADS,
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            payload={
                "limit": payload.limit,
                "include_dead_end": payload.include_dead_end,
            },
        )
    return {"ok": True, "job_id": job.id, "candidates": len(candidates)}


# ─── SSE stream eventow + jobs ───────────────────────────────────────────

# Tunables
SSE_POLL_INTERVAL_S = float(os.getenv("SSE_POLL_INTERVAL", "2"))
SSE_HEARTBEAT_S = float(os.getenv("SSE_HEARTBEAT", "15"))
SSE_MAX_CONNECTION_S = float(os.getenv("SSE_MAX_CONNECTION", "300"))  # 5min - przegladarka odnowi


def _sse_format(event_type: str, data: dict) -> str:
    """Format Server-Sent Event: type: foo\\ndata: {...}\\n\\n"""
    return f"event: {event_type}\ndata: {_json.dumps(data, default=str)}\n\n"


@app.get("/api/events/stream")
async def events_stream(
    request: Request,
    token: str = Query("", description="Auth token (EventSource nie wspiera headerow). Opcjonalny - cookie fallback dziala tez."),
):
    """Server-Sent Events: live stream nowych eventow + zmian jobow per workspace.

    Frontend uzywa zamiast pollingu jobs/events co 2-8s. EventSource w browser
    nie wspiera customowych headerow, dlatego token leci albo jako query param
    (Bearer mode) albo automatycznie z cookie (cookie mode - browser sam dolacza).

    Strumien emituje:
      event: event     -> nowy wpis w Event table (research done, draft gen, etc.)
      event: job       -> zmiana statusu Joba (pending->running->done/failed)
      event: heartbeat -> co SSE_HEARTBEAT_S sekund (zeby proxy nie ucial)

    Jak SSE pad (proxy, mobile background), frontend wraca do pollingu.
    Auto-close po SSE_MAX_CONNECTION_S sekundach - przegladarka sama otworzy nowy.
    """
    # Auth: najpierw query token (Bearer mode), potem cookie (cookie-only mode)
    auth_token = token or request.cookies.get(COOKIE_NAME, "")
    payload = verify_token(auth_token) if auth_token else None
    if not payload:
        raise HTTPException(status_code=401, detail="Brak autoryzacji.")
    ws_id = payload.get("workspace_id")
    if not ws_id:
        raise HTTPException(status_code=401, detail="Workspace nie wybrany.")

    async def gen():
        # Start od najnowszego znanego ID - nie spamujemy historii.
        last_event_id = 0
        # Job statuses w pamieci - emitujemy "job" event tylko na zmiane.
        job_states: dict[int, str] = {}
        try:
            with SessionLocal() as session:
                last_row = session.execute(
                    select(Event.id).where(Event.workspace_id == ws_id)
                    .order_by(desc(Event.id)).limit(1)
                ).scalar_one_or_none()
                last_event_id = int(last_row or 0)
                # Wstepny snapshot aktywnych jobow
                active = session.execute(
                    select(Job).where(
                        Job.workspace_id == ws_id,
                        Job.status.in_(["pending", "running"]),
                    )
                ).scalars().all()
                for j in active:
                    job_states[j.id] = j.status
                    yield _sse_format("job", {
                        "id": j.id, "type": j.type, "status": j.status,
                        "progress": j.progress, "total": j.total,
                    })

            yield _sse_format("ready", {"last_event_id": last_event_id})

            start_ts = asyncio.get_event_loop().time()
            last_heartbeat = start_ts
            while True:
                # Klient sie rozlaczyl
                if await request.is_disconnected():
                    break
                # Limit czasu polaczenia (zeby zlap proxy timeouty + browser auto-recover)
                now = asyncio.get_event_loop().time()
                if now - start_ts > SSE_MAX_CONNECTION_S:
                    yield _sse_format("reconnect", {"reason": "max-connection-age"})
                    break

                # Pobierz nowe eventy + sprawdz zmiany jobow
                with SessionLocal() as session:
                    new_events = session.execute(
                        select(Event)
                        .where(Event.workspace_id == ws_id, Event.id > last_event_id)
                        .order_by(Event.id.asc()).limit(50)
                    ).scalars().all()
                    for e in new_events:
                        last_event_id = e.id
                        yield _sse_format("event", {
                            "id": e.id,
                            "type": e.type,
                            "level": e.level,
                            "source": e.source,
                            "message": e.message,
                            "lead_id": e.lead_id,
                            "created_at": iso_utc(e.created_at),
                        })
                    # Snapshot biezacych jobow workspace'u
                    current_jobs = session.execute(
                        select(Job).where(Job.workspace_id == ws_id)
                        .order_by(desc(Job.id)).limit(20)
                    ).scalars().all()
                    seen_ids = set()
                    for j in current_jobs:
                        seen_ids.add(j.id)
                        prev = job_states.get(j.id)
                        # Emituj jak nowy ALBO zmiana statusu/progresu
                        if prev != j.status or j.status in ("pending", "running"):
                            job_states[j.id] = j.status
                            yield _sse_format("job", {
                                "id": j.id, "type": j.type, "status": j.status,
                                "progress": j.progress, "total": j.total,
                            })
                    # Posprzataj job_states dla nieobecnych (mogly byc starsze niz limit)
                    for stale_id in list(job_states.keys()):
                        if stale_id not in seen_ids:
                            del job_states[stale_id]

                # Heartbeat (zeby proxy / load balancer nie ucial idle)
                if now - last_heartbeat >= SSE_HEARTBEAT_S:
                    last_heartbeat = now
                    yield _sse_format("heartbeat", {"t": now})

                await asyncio.sleep(SSE_POLL_INTERVAL_S)
        except asyncio.CancelledError:
            # Klient rozlaczyl sie - normalne zakonczenie
            pass
        except Exception as exc:
            log.exception(f"SSE stream error for ws={ws_id}: {exc}")
            yield _sse_format("error", {"detail": str(exc)[:200]})

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Nginx: nie buforuj
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


# ─── Jobs polling ────────────────────────────────────────────────────────

@app.get("/api/jobs")
def list_jobs(
    status: str | None = None, limit: int = 30, lite: bool = True,
    cur: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Lista jobow workspace'u. Default lite=True - bez payload/result, lekkie
    dla auto-refresh polling. Detail przez /api/jobs/{id} albo lite=false."""
    limit = max(1, min(limit, 100))
    with SessionLocal() as session:
        q = select(Job).where(Job.workspace_id == cur.workspace_id) \
            .order_by(desc(Job.created_at)).limit(limit)
        if status: q = q.where(Job.status == status)
        jobs = session.execute(q).scalars().all()
        return [serialize_job(j, lite=lite) for j in jobs]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    with SessionLocal() as session:
        job = session.execute(
            select(Job).where(Job.id == job_id, Job.workspace_id == cur.workspace_id)
        ).scalar_one_or_none()
        if job is None: raise HTTPException(status_code=404, detail="Job nie istnieje.")
        return serialize_job(job)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    with SessionLocal() as session:
        job = session.execute(
            select(Job).where(Job.id == job_id, Job.workspace_id == cur.workspace_id)
        ).scalar_one_or_none()
        if job is None: raise HTTPException(status_code=404, detail="Job nie istnieje.")
        if job.status not in [JobStatus.PENDING.value, JobStatus.RUNNING.value]:
            raise HTTPException(status_code=400, detail="Job nie jest aktywny.")
        job.status = JobStatus.CANCELLED.value
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
        return {"ok": True}


# ─── Patrol (autonomiczny agent) ─────────────────────────────────────────

class PatrolIn(BaseModel):
    """Config patrola - user-facing. Worker odpala wedlug schedule."""
    name: str
    enabled: bool = True
    segments: list[str] = []
    locations: list[str] = []
    sources: list[str] = ["google_places"]
    custom_target: str | None = None
    max_per_run: int = 10
    cap_per_day: int = 30
    frequency_hours: int = 12
    relevance_threshold: int = 6
    auto_draft_threshold: int | None = None


def _serialize_patrol(p: PatrolSchedule) -> dict[str, Any]:
    return {
        "id": p.id, "name": p.name, "enabled": bool(p.enabled),
        "segments": p.segments or [], "locations": p.locations or [],
        "sources": p.sources or [], "custom_target": p.custom_target,
        "max_per_run": p.max_per_run, "cap_per_day": p.cap_per_day,
        "frequency_hours": p.frequency_hours,
        "relevance_threshold": p.relevance_threshold,
        "auto_draft_threshold": p.auto_draft_threshold,
        "runs_today": p.runs_today, "total_runs": p.total_runs,
        "total_leads_found": p.total_leads_found,
        "last_run_at": iso_utc(p.last_run_at),
        "next_run_at": iso_utc(p.next_run_at),
        "created_at": iso_utc(p.created_at),
    }


@app.get("/api/patrol")
def list_patrols(cur: CurrentUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Lista patroli workspace'u. Default sort: enabled first, potem name."""
    with SessionLocal() as session:
        rows = session.execute(
            select(PatrolSchedule)
            .where(PatrolSchedule.workspace_id == cur.workspace_id)
            .order_by(desc(PatrolSchedule.enabled), PatrolSchedule.name)
        ).scalars().all()
        return [_serialize_patrol(p) for p in rows]


@app.post("/api/patrol")
def create_patrol(payload: PatrolIn, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Utworz nowy patrol. next_run_at = now (uruchomi sie przy nastepnym ticku)."""
    name = (payload.name or "").strip()[:255]
    if not name:
        raise HTTPException(status_code=400, detail="Nazwa patrola wymagana.")
    if not payload.segments and not payload.custom_target:
        raise HTTPException(
            status_code=400,
            detail="Wybierz segment lub podaj custom_target."
        )
    with SessionLocal() as session:
        p = PatrolSchedule(
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            name=name, enabled=payload.enabled,
            segments=payload.segments, locations=payload.locations,
            sources=payload.sources, custom_target=payload.custom_target,
            max_per_run=max(1, min(payload.max_per_run, 100)),
            cap_per_day=max(1, min(payload.cap_per_day, 500)),
            frequency_hours=max(1, min(payload.frequency_hours, 168)),
            relevance_threshold=max(0, min(payload.relevance_threshold, 10)),
            auto_draft_threshold=payload.auto_draft_threshold,
            next_run_at=datetime.now(timezone.utc),
        )
        session.add(p)
        session.commit()
        session.refresh(p)
        return _serialize_patrol(p)


@app.patch("/api/patrol/{patrol_id}")
def update_patrol(
    patrol_id: int, payload: PatrolIn,
    cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    with SessionLocal() as session:
        p = session.execute(
            select(PatrolSchedule).where(
                PatrolSchedule.id == patrol_id,
                PatrolSchedule.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if p is None:
            raise HTTPException(status_code=404, detail="Patrol nie istnieje.")
        p.name = (payload.name or p.name).strip()[:255]
        p.enabled = payload.enabled
        p.segments = payload.segments
        p.locations = payload.locations
        p.sources = payload.sources
        p.custom_target = payload.custom_target
        p.max_per_run = max(1, min(payload.max_per_run, 100))
        p.cap_per_day = max(1, min(payload.cap_per_day, 500))
        p.frequency_hours = max(1, min(payload.frequency_hours, 168))
        p.relevance_threshold = max(0, min(payload.relevance_threshold, 10))
        p.auto_draft_threshold = payload.auto_draft_threshold
        session.commit()
        return _serialize_patrol(p)


@app.delete("/api/patrol/{patrol_id}")
def delete_patrol(patrol_id: int, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    with SessionLocal() as session:
        p = session.execute(
            select(PatrolSchedule).where(
                PatrolSchedule.id == patrol_id,
                PatrolSchedule.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if p is None:
            raise HTTPException(status_code=404, detail="Patrol nie istnieje.")
        session.delete(p)
        session.commit()
        return {"ok": True}


@app.post("/api/patrol/{patrol_id}/run-now")
def run_patrol_now(patrol_id: int, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Force-run: ustaw next_run_at = now, patrol odpali sie przy najblizszym
    ticku workera (max 60s). Cap_per_day nadal pilnowany."""
    with SessionLocal() as session:
        p = session.execute(
            select(PatrolSchedule).where(
                PatrolSchedule.id == patrol_id,
                PatrolSchedule.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if p is None:
            raise HTTPException(status_code=404, detail="Patrol nie istnieje.")
        if not p.enabled:
            raise HTTPException(status_code=400, detail="Patrol jest wyłączony - włącz go najpierw.")
        p.next_run_at = datetime.now(timezone.utc)
        session.commit()
        return {"ok": True, "msg": "Patrol uruchomi się w ciągu max 60s."}


# ─── Woodpecker ──────────────────────────────────────────────────────────

@app.get("/api/woodpecker/campaigns")
def woodpecker_campaigns(cur: CurrentUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    from agent.woodpecker import has_woodpecker_key, list_campaigns
    if not has_woodpecker_key(): return []
    try:
        return [{"id": c.id, "name": c.name, "status": c.status} for c in list_campaigns()]
    except Exception as exc:
        log.warning(f"Woodpecker campaigns failed: {exc}")
        return []
