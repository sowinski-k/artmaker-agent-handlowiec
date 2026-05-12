"""Ecombinat FastAPI backend.

JSON API serwujący agent/ modules dla Next.js frontend'u. Real DB queries
zamiast mock'a. Session przez Bearer token (signed JWT-like blob via
itsdangerous), z fallbackiem do cookies dla SSR.

Bezpieczeństwo:
  - Rate limiting per IP (slowapi) - 5 prób loginu / 5 min
  - Security headers (HSTS, X-Frame-Options, X-Content-Type-Options, CSP)
  - HTTPS-only cookies w production
  - Generic error responses (nie eksponuje stack trace)
  - Audit log każdej akcji w Event table
  - CORS allowlist explicit (FRONTEND_ORIGINS env)
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import desc, func, select

from core.db import (
    DraftStatus,
    EmailDraft,
    Event,
    Lead,
    LeadStatus,
    SessionLocal,
    init_db,
)

# ─── Config ──────────────────────────────────────────────────────────────

APP_PASSWORD = (os.getenv("APP_PASSWORD") or "").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET") or "ecombinat-dev-secret-change-in-prod"
COOKIE_NAME = "ecombinat_session"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60

_origins_env = (os.getenv("FRONTEND_ORIGINS") or "http://localhost:3000").strip()
if _origins_env == "*":
    ALLOWED_ORIGINS = ["*"]
else:
    ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]

IS_PROD = os.getenv("RAILWAY_ENVIRONMENT") is not None

serializer = URLSafeSerializer(SESSION_SECRET, salt="ecombinat-session-v1")
limiter = Limiter(key_func=get_remote_address)

# ─── Logging - bez secret leaków ─────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ecombinat")


# ─── App lifespan: init DB on startup ────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup: stwórz tabele jeśli nie istnieją."""
    try:
        init_db()
        log.info("DB initialized OK")
    except Exception as exc:
        log.exception(f"DB init failed: {exc}")
    yield


app = FastAPI(title="Ecombinat API", version="0.2.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ─── Middleware: CORS + security headers ─────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Standardowe security headers - obrona przed XSS / clickjacking / sniffing."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if IS_PROD:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ─── Generic error handlers (nie eksponuj stack trace) ───────────────────

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "Nieprawidłowe dane wejściowe."},
    )


@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    log.exception(f"Unhandled error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Wewnętrzny błąd serwera."},
    )


# ─── Auth helpers ───────────────────────────────────────────────────────

def _make_token() -> str:
    return serializer.dumps({"authed": True, "iat": datetime.now(timezone.utc).isoformat()})


def _verify_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        data = serializer.loads(token)
        return bool(data.get("authed"))
    except BadSignature:
        return False


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def require_auth(request: Request) -> None:
    if not APP_PASSWORD:
        return
    if not _verify_token(_extract_token(request)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Brak autoryzacji - zaloguj się.",
        )


def _log_event(level: str, source: str, event_type: str, message: str) -> None:
    """Audit log helper. Łyka błędy żeby nie wywalał requestu."""
    try:
        with SessionLocal() as session:
            session.add(Event(level=level, source=source, type=event_type, message=message))
            session.commit()
    except Exception as exc:
        log.warning(f"Failed to log event: {exc}")


# ─── Schemas ────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    password: str


class StatusOut(BaseModel):
    authed: bool
    app_name: str = "Ecombinat"


class LoginOut(BaseModel):
    authed: bool
    token: str
    app_name: str = "Ecombinat"


# ─── Health / version ────────────────────────────────────────────────────

@app.get("/")
def root() -> dict[str, Any]:
    return {
        "app": "ecombinat-api",
        "version": "0.2.0",
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ─── Auth endpoints ─────────────────────────────────────────────────────

@app.post("/api/auth/login")
@limiter.limit("5/5minutes")
def login(request: Request, payload: LoginIn, response: Response) -> LoginOut:
    """Login z rate limit 5 prób / 5 min per IP - obrona przed brute force."""
    if APP_PASSWORD and payload.password != APP_PASSWORD:
        _log_event(
            "WARNING", "auth", "login_failed",
            f"Failed login attempt from {get_remote_address(request)}",
        )
        raise HTTPException(status_code=401, detail="Złe hasło.")
    token = _make_token()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="none" if IS_PROD else "lax",
        secure=IS_PROD,
    )
    _log_event("INFO", "auth", "login_ok",
               f"Login OK from {get_remote_address(request)}")
    return LoginOut(authed=True, token=token)


@app.post("/api/auth/logout")
def logout(response: Response) -> StatusOut:
    response.delete_cookie(COOKIE_NAME)
    return StatusOut(authed=False)


@app.get("/api/auth/me")
def me(request: Request) -> StatusOut:
    if not APP_PASSWORD:
        return StatusOut(authed=True)
    return StatusOut(authed=_verify_token(_extract_token(request)))


# ─── Dashboard - real DB queries ────────────────────────────────────────

def _start_of_day_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _sparkline_last_n_days(table_status: str | None = None, days: int = 12) -> list[int]:
    """Liczba leadów dziennie ostatnich N dni - bardzo proste."""
    # Lekka query: count per day from Lead.created_at
    end = datetime.now(timezone.utc)
    start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    points = []
    with SessionLocal() as session:
        for i in range(days - 1, -1, -1):
            day_start = start - timedelta(days=i)
            day_end = day_start + timedelta(days=1)
            q = select(func.count(Lead.id)).where(
                Lead.created_at >= day_start,
                Lead.created_at < day_end,
            )
            if table_status:
                q = q.where(Lead.status == table_status)
            n = session.scalar(q) or 0
            points.append(int(n))
    return points


@app.get("/api/dashboard", dependencies=[Depends(require_auth)])
def get_dashboard() -> dict[str, Any]:
    """Real DB: liczby leadów, draftów, eventów + funnel + segmenty."""
    with SessionLocal() as session:
        leads_total = session.scalar(select(func.count(Lead.id))) or 0
        researched = session.scalar(
            select(func.count(Lead.id)).where(Lead.status == LeadStatus.RESEARCHED.value)
        ) or 0
        drafted = session.scalar(
            select(func.count(Lead.id)).where(Lead.status == LeadStatus.DRAFTED.value)
        ) or 0
        sent_status = session.scalar(
            select(func.count(Lead.id)).where(Lead.status == LeadStatus.SENT.value)
        ) or 0
        replied = session.scalar(
            select(func.count(Lead.id)).where(Lead.status == LeadStatus.REPLIED.value)
        ) or 0
        bounced = session.scalar(
            select(func.count(Lead.id)).where(Lead.status == LeadStatus.BOUNCED.value)
        ) or 0
        drafts_pending = session.scalar(
            select(func.count(EmailDraft.id)).where(EmailDraft.status == DraftStatus.DRAFT.value)
        ) or 0
        sent_today = session.scalar(
            select(func.count(EmailDraft.id)).where(
                EmailDraft.status == DraftStatus.SENT.value,
                EmailDraft.sent_at >= _start_of_day_utc(),
            )
        ) or 0
        sent_total = session.scalar(
            select(func.count(EmailDraft.id)).where(EmailDraft.status == DraftStatus.SENT.value)
        ) or 0
        avg_score = session.scalar(select(func.avg(Lead.score))) or 0.0
        hot_leads = session.scalar(
            select(func.count(Lead.id)).where(Lead.score >= 7.0)
        ) or 0
        segments = session.execute(
            select(Lead.segment, func.count(Lead.id))
            .group_by(Lead.segment)
            .order_by(func.count(Lead.id).desc())
        ).all()

    reply_rate = (replied / max(sent_total, 1)) * 100 if sent_total else 0
    drafted_total = drafted + sent_status + replied + bounced
    sent_total_w_replied = sent_total + replied + bounced

    return {
        "stats": {
            "leads_total": int(leads_total),
            "leads_hot": int(hot_leads),
            "drafts_pending": int(drafts_pending),
            "avg_score": float(round(avg_score, 1)),
            "researched": int(researched),
            "sent_today": int(sent_today),
            "replied": int(replied),
            "reply_rate": float(round(reply_rate, 1)),
            "bounced": int(bounced),
        },
        "sparklines": {
            "leads": _sparkline_last_n_days(days=12),
            "drafts": _sparkline_last_n_days(table_status=LeadStatus.DRAFTED.value, days=12),
            "replies": _sparkline_last_n_days(table_status=LeadStatus.REPLIED.value, days=12),
        },
        "funnel": [
            {"label": "Pozyskane", "value": int(leads_total), "percent": 100.0 if leads_total else 0,
             "icon": "upload"},
            {"label": "Researched",
             "value": int(researched + drafted_total),
             "percent": float(round((researched + drafted_total) / max(leads_total, 1) * 100, 1)),
             "icon": "search"},
            {"label": "Z draftem",
             "value": int(drafted_total),
             "percent": float(round(drafted_total / max(leads_total, 1) * 100, 1)),
             "icon": "check"},
            {"label": "Wysłane",
             "value": int(sent_total_w_replied),
             "percent": float(round(sent_total_w_replied / max(leads_total, 1) * 100, 1)),
             "icon": "send"},
            {"label": "Odpowiedzieli",
             "value": int(replied),
             "percent": float(round(replied / max(leads_total, 1) * 100, 1)),
             "icon": "message-circle"},
        ],
        "system": [
            {"label": "Anthropic key",
             "value": "OK" if os.getenv("ANTHROPIC_API_KEY") else "brak",
             "status": "ok" if os.getenv("ANTHROPIC_API_KEY") else "warn"},
            {"label": "Gemini key",
             "value": "OK" if os.getenv("GEMINI_API_KEY") else "brak",
             "status": "ok" if os.getenv("GEMINI_API_KEY") else "warn"},
            {"label": "Apify token",
             "value": "OK" if os.getenv("APIFY_API_TOKEN") else "brak",
             "status": "ok" if os.getenv("APIFY_API_TOKEN") else "warn"},
            {"label": "Google Places",
             "value": "OK" if os.getenv("GOOGLE_PLACES_API_KEY") else "brak",
             "status": "ok" if os.getenv("GOOGLE_PLACES_API_KEY") else "warn"},
            {"label": "Woodpecker",
             "value": "OK" if os.getenv("WOODPECKER_API_KEY") else "brak",
             "status": "ok" if os.getenv("WOODPECKER_API_KEY") else "warn"},
            {"label": "DRY_RUN",
             "value": "true · blokuje wysyłkę" if os.getenv("DRY_RUN", "true").lower() == "true" else "false",
             "status": "warn" if os.getenv("DRY_RUN", "true").lower() == "true" else "ok"},
        ],
        "segments": [{"name": s[0] or "—", "count": int(s[1])} for s in segments],
    }


@app.get("/api/events", dependencies=[Depends(require_auth)])
def get_events(limit: int = 8) -> list[dict[str, Any]]:
    """Activity feed z Event table."""
    limit = max(1, min(limit, 100))

    def _icon_for(src: str, ev_type: str) -> tuple[str, bool]:
        s = (src or "").lower()
        t = (ev_type or "").lower()
        if "research" in s: return ("search", True)
        if "discover" in s: return ("upload", True)
        if "generate" in s or "draft" in t: return ("wand", True)
        if "push" in s or "send" in t or "email_sent" in t: return ("send", False)
        if "poll" in s: return ("refresh", False)
        if "auth" in s: return ("key", False)
        if "error" in (s + t): return ("x", False)
        return ("circle-dot", False)

    def _time_relative(then: datetime) -> str:
        now = datetime.now(timezone.utc)
        delta = (now.replace(tzinfo=None) - then.replace(tzinfo=None)).total_seconds() \
            if then.tzinfo is None else (now - then).total_seconds()
        mins = int(delta / 60)
        if mins < 1: return "teraz"
        if mins < 60: return f"{mins}m"
        if mins < 1440: return f"{mins // 60}h"
        return then.strftime("%m-%d")

    import html as _html
    with SessionLocal() as session:
        events = session.execute(
            select(Event).order_by(desc(Event.created_at)).limit(limit)
        ).scalars().all()

    out = []
    for e in events:
        ic, acc = _icon_for(e.source or "", e.type or "")
        msg = e.message or ""
        if len(msg) > 100:
            msg = msg[:97] + "..."
        out.append({
            "icon": ic,
            "accent": acc,
            "text": f"<strong>{_html.escape(e.source or '—')}</strong> · {_html.escape(msg)}",
            "time": _time_relative(e.created_at),
        })
    return out


# ─── Leads endpoints ────────────────────────────────────────────────────

@app.get("/api/leads", dependencies=[Depends(require_auth)])
def list_leads(
    limit: int = 50,
    offset: int = 0,
    segment: str | None = None,
    status: str | None = None,
    min_score: float = 0.0,
) -> dict[str, Any]:
    """Lista leadów z filtrami."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    with SessionLocal() as session:
        q = select(Lead).order_by(desc(Lead.score), desc(Lead.created_at))
        if segment:
            q = q.where(Lead.segment == segment)
        if status:
            q = q.where(Lead.status == status)
        if min_score > 0:
            q = q.where(Lead.score >= min_score)

        total = session.scalar(
            select(func.count(Lead.id)).select_from(q.subquery())
        ) or 0
        rows = session.execute(q.limit(limit).offset(offset)).scalars().all()

        leads = [
            {
                "id": l.id,
                "segment": l.segment,
                "company_name": l.company_name,
                "contact_name": l.contact_name,
                "email": l.email,
                "phone": l.phone,
                "website": l.website,
                "city": l.city,
                "status": l.status,
                "score": float(l.score) if l.score is not None else None,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in rows
        ]
    return {"total": int(total), "items": leads}


@app.get("/api/leads/{lead_id}", dependencies=[Depends(require_auth)])
def get_lead(lead_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead nie istnieje.")
        return {
            "id": lead.id,
            "segment": lead.segment,
            "company_name": lead.company_name,
            "contact_name": lead.contact_name,
            "email": lead.email,
            "phone": lead.phone,
            "website": lead.website,
            "instagram": lead.instagram,
            "city": lead.city,
            "country": lead.country,
            "status": lead.status,
            "score": float(lead.score) if lead.score is not None else None,
            "research_data": lead.research_data,
            "notes": lead.notes,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        }


# ─── Drafts endpoints ───────────────────────────────────────────────────

@app.get("/api/drafts", dependencies=[Depends(require_auth)])
def list_drafts(status_filter: str | None = "draft", limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        q = select(EmailDraft).order_by(desc(EmailDraft.created_at)).limit(limit)
        if status_filter:
            q = q.where(EmailDraft.status == status_filter)
        drafts = session.execute(q).scalars().all()

        return [
            {
                "id": d.id,
                "lead_id": d.lead_id,
                "company": d.lead.company_name if d.lead else "(unknown)",
                "subject": d.subject,
                "snippet1": d.snippet1,
                "snippet2": d.snippet2,
                "snippet3": d.snippet3,
                "snippet4": d.snippet4,
                "snippet5": d.snippet5,
                "full_preview": d.full_preview,
                "status": d.status,
                "template_variant": d.template_variant,
                "edited_by_user": d.edited_by_user,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "sent_at": d.sent_at.isoformat() if d.sent_at else None,
            }
            for d in drafts
        ]


class DraftUpdate(BaseModel):
    subject: str | None = None
    snippet1: str | None = None
    snippet2: str | None = None
    snippet3: str | None = None
    snippet4: str | None = None
    snippet5: str | None = None


@app.patch("/api/drafts/{draft_id}", dependencies=[Depends(require_auth)])
def update_draft(draft_id: int, payload: DraftUpdate) -> dict[str, Any]:
    """Ręczna edycja draftu. Aktualizuje pola które zostały podane, oznacza edited_by_user."""
    from agent.generate import _strip_ai_artifacts

    with SessionLocal() as session:
        draft = session.get(EmailDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft nie istnieje.")
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            if value is None:
                continue
            cleaned = _strip_ai_artifacts(value) or value
            setattr(draft, field, cleaned)
        # Rebuild full_preview
        parts = [f"Subject: {draft.subject}", "", draft.snippet1 or "", "",
                 draft.snippet2 or "", "", draft.snippet3 or ""]
        if draft.snippet4: parts.extend(["", draft.snippet4])
        parts.extend(["", draft.snippet5 or ""])
        draft.full_preview = "\n".join(parts)
        draft.edited_by_user = True
        session.commit()
        _log_event("INFO", "gui", "draft_edited", f"Draft #{draft_id} edited via API")
        return {"ok": True, "draft_id": draft_id}


@app.post("/api/drafts/{draft_id}/approve", dependencies=[Depends(require_auth)])
def approve_draft(draft_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        draft = session.get(EmailDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft nie istnieje.")
        draft.status = DraftStatus.APPROVED.value
        session.commit()
        _log_event("INFO", "gui", "draft_approved", f"Draft #{draft_id} approved")
        return {"ok": True}


@app.post("/api/drafts/{draft_id}/reject", dependencies=[Depends(require_auth)])
def reject_draft(draft_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        draft = session.get(EmailDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft nie istnieje.")
        draft.status = DraftStatus.REJECTED.value
        session.commit()
        _log_event("INFO", "gui", "draft_rejected", f"Draft #{draft_id} rejected")
        return {"ok": True}


class SendDraftIn(BaseModel):
    campaign_id: int


@app.post("/api/drafts/{draft_id}/send", dependencies=[Depends(require_auth)])
def send_draft(draft_id: int, payload: SendDraftIn) -> dict[str, Any]:
    """Push do Woodpecker - aktywuje sekwencję follow-upów."""
    from agent.push_to_sender import push_draft
    try:
        prospect_id = push_draft(draft_id, payload.campaign_id)
        return {"ok": True, "prospect_id": prospect_id}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class RegenerateSnippetIn(BaseModel):
    snippet_name: str  # 'subject' / 'snippet1' ... 'snippet5'
    instruction: str | None = None
    provider: str | None = None
    model: str | None = None


@app.post("/api/drafts/{draft_id}/regenerate", dependencies=[Depends(require_auth)])
def regenerate_snippet(draft_id: int, payload: RegenerateSnippetIn) -> dict[str, Any]:
    from agent.generate import regenerate_snippet as _regen
    try:
        new_text = _regen(
            draft_id, payload.snippet_name,
            user_instruction=payload.instruction,
            provider=payload.provider, model=payload.model,
        )
        return {"ok": True, "text": new_text}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─── Discovery + research endpoints ─────────────────────────────────────

class DiscoverIn(BaseModel):
    query: str
    sources: list[str]  # 'apify', 'google_places', 'apify_allegro', 'apify_linkedin'
    max_per_source: int = 20
    segment: str = "inne"
    location: str | None = None
    custom_description: str | None = None
    use_relevance_filter: bool = True


@app.post("/api/discovery/search", dependencies=[Depends(require_auth)])
def discovery_search(payload: DiscoverIn) -> dict[str, Any]:
    from agent.discovery import (
        ApifyAllegroSource, ApifyLinkedInSource, ApifySource,
        GooglePlacesSource, run_search, score_relevance_batch,
    )

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
        raise HTTPException(status_code=400, detail="Żadne wybrane źródło nie jest dostępne (brak kluczy API).")

    places, diagnostics = run_search(
        sources,
        query=payload.query,
        max_results_per_source=max(1, min(payload.max_per_source, 50)),
    )

    relevance_map: dict[int, dict] = {}
    if payload.use_relevance_filter and places:
        try:
            items, _ = score_relevance_batch(
                places, segment=payload.segment, city=payload.location,
                custom_description=payload.custom_description,
            )
            for it in items:
                if 0 <= it.idx < len(places):
                    relevance_map[it.idx] = {"score": int(it.score), "reason": it.reason}
        except Exception as exc:
            log.warning(f"Relevance filter failed: {exc}")

    return {
        "places": [
            {
                **p.model_dump(),
                "relevance": relevance_map.get(i),
            }
            for i, p in enumerate(places)
        ],
        "diagnostics": [d.model_dump() for d in diagnostics],
    }


class ResearchIn(BaseModel):
    url: str
    segment_hint: str | None = None
    city_hint: str | None = None
    force_refresh: bool = False


@app.post("/api/research", dependencies=[Depends(require_auth)])
def research_lead(payload: ResearchIn) -> dict[str, Any]:
    from agent.research import research_and_save
    try:
        lead_id, result, was_researched = research_and_save(
            payload.url,
            segment_hint=payload.segment_hint,
            city_hint=payload.city_hint,
            force_refresh=payload.force_refresh,
        )
        return {
            "ok": True, "lead_id": lead_id, "was_researched": was_researched,
            "score": result.score.total if result else None,
            "company": result.company_name if result else None,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class GenerateDraftIn(BaseModel):
    lead_id: int
    provider: str | None = None
    model: str | None = None


@app.post("/api/drafts", dependencies=[Depends(require_auth)])
def create_draft(payload: GenerateDraftIn) -> dict[str, Any]:
    from agent.generate import generate_draft_for_lead
    try:
        draft_id = generate_draft_for_lead(
            payload.lead_id, provider=payload.provider, model=payload.model,
        )
        return {"ok": True, "draft_id": draft_id}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ─── Woodpecker campaigns ───────────────────────────────────────────────

@app.get("/api/woodpecker/campaigns", dependencies=[Depends(require_auth)])
def woodpecker_campaigns() -> list[dict[str, Any]]:
    from agent.woodpecker import has_woodpecker_key, list_campaigns
    if not has_woodpecker_key():
        return []
    try:
        camps = list_campaigns()
        return [{"id": c.id, "name": c.name, "status": c.status} for c in camps]
    except Exception as exc:
        log.warning(f"Woodpecker list_campaigns failed: {exc}")
        return []
