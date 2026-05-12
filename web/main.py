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
from pydantic import BaseModel, EmailStr
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import desc, func, select

from core.db import (
    DraftStatus,
    EmailDraft,
    Event,
    Job,
    JobStatus,
    JobType,
    Lead,
    LeadStatus,
    SessionLocal,
    User,
    Workspace,
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
)
from web.jobs_dispatcher import create_job, serialize_job


# ─── Config ──────────────────────────────────────────────────────────────

_origins_env = (os.getenv("FRONTEND_ORIGINS") or "http://localhost:3000").strip()
ALLOWED_ORIGINS = ["*"] if _origins_env == "*" else [
    o.strip() for o in _origins_env.split(",") if o.strip()
]
IS_PROD = os.getenv("RAILWAY_ENVIRONMENT") is not None

limiter = Limiter(key_func=get_remote_address)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ecombinat")


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
        # Cookie fallback dla SSR
        response.set_cookie(
            key=COOKIE_NAME, value=token,
            max_age=COOKIE_MAX_AGE, httponly=True,
            samesite="none" if IS_PROD else "lax", secure=IS_PROD,
        )
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
            select(Workspace).join(
                Workspace.__table__.join(
                    __import__("core.db", fromlist=["WorkspaceMember"]).WorkspaceMember.__table__,
                    Workspace.id == __import__("core.db", fromlist=["WorkspaceMember"]).WorkspaceMember.workspace_id,
                )
            ).where(
                __import__("core.db", fromlist=["WorkspaceMember"]).WorkspaceMember.user_id == user.id,
            ).order_by(Workspace.created_at.desc())
        ).scalars().first()

        if ws is None:
            # Defensywnie: owned ale brak member - sprawdź ownership
            ws = session.execute(
                select(Workspace).where(Workspace.owner_user_id == user.id)
                .order_by(Workspace.created_at.desc())
            ).scalars().first()

        if ws is None:
            raise HTTPException(status_code=500, detail="Brak workspace - skontaktuj się z administratorem.")

        user.last_login_at = datetime.now(timezone.utc)
        session.commit()

        token = make_token(user.id, ws.id)
        response.set_cookie(
            key=COOKIE_NAME, value=token,
            max_age=COOKIE_MAX_AGE, httponly=True,
            samesite="none" if IS_PROD else "lax", secure=IS_PROD,
        )
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
    response.delete_cookie(COOKIE_NAME)
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


# ─── Dashboard - filtrowane by workspace ────────────────────────────────

def _start_of_day_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _sparkline_for_ws(workspace_id: int, status: str | None = None, days: int = 12) -> list[int]:
    from datetime import timedelta
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    points = []
    with SessionLocal() as session:
        for i in range(days - 1, -1, -1):
            day_start = end - timedelta(days=i)
            day_end = day_start + timedelta(days=1)
            q = select(func.count(Lead.id)).where(
                Lead.workspace_id == workspace_id,
                Lead.created_at >= day_start, Lead.created_at < day_end,
            )
            if status: q = q.where(Lead.status == status)
            points.append(int(session.scalar(q) or 0))
    return points


@app.get("/api/dashboard")
def get_dashboard(cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    ws_id = cur.workspace_id
    with SessionLocal() as session:
        def cnt(*conds): return int(session.scalar(
            select(func.count(Lead.id)).where(Lead.workspace_id == ws_id, *conds)
        ) or 0)
        def cnt_d(*conds): return int(session.scalar(
            select(func.count(EmailDraft.id)).where(EmailDraft.workspace_id == ws_id, *conds)
        ) or 0)

        leads_total = cnt()
        researched = cnt(Lead.status == LeadStatus.RESEARCHED.value)
        drafted = cnt(Lead.status == LeadStatus.DRAFTED.value)
        sent_lead = cnt(Lead.status == LeadStatus.SENT.value)
        replied = cnt(Lead.status == LeadStatus.REPLIED.value)
        bounced = cnt(Lead.status == LeadStatus.BOUNCED.value)
        drafts_pending = cnt_d(EmailDraft.status == DraftStatus.DRAFT.value)
        sent_today = cnt_d(EmailDraft.status == DraftStatus.SENT.value,
                          EmailDraft.sent_at >= _start_of_day_utc())
        sent_total = cnt_d(EmailDraft.status == DraftStatus.SENT.value)
        avg_score = float(session.scalar(
            select(func.avg(Lead.score)).where(Lead.workspace_id == ws_id)
        ) or 0.0)
        hot_leads = cnt(Lead.score >= 7.0)

        segments = session.execute(
            select(Lead.segment, func.count(Lead.id))
            .where(Lead.workspace_id == ws_id)
            .group_by(Lead.segment)
            .order_by(func.count(Lead.id).desc())
        ).all()

        running_jobs = int(session.scalar(
            select(func.count(Job.id)).where(
                Job.workspace_id == ws_id,
                Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
            )
        ) or 0)

    reply_rate = (replied / max(sent_total, 1)) * 100 if sent_total else 0
    drafted_total = drafted + sent_lead + replied + bounced
    sent_total_w = sent_total + replied + bounced

    return {
        "workspace": {"id": ws_id, "name": cur.workspace_name, "plan": cur.workspace_plan},
        "stats": {
            "leads_total": leads_total, "leads_hot": hot_leads,
            "drafts_pending": drafts_pending, "avg_score": round(avg_score, 1),
            "researched": researched, "sent_today": sent_today,
            "replied": replied, "reply_rate": round(reply_rate, 1),
            "bounced": bounced, "running_jobs": running_jobs,
        },
        "sparklines": {
            "leads": _sparkline_for_ws(ws_id, days=12),
            "drafts": _sparkline_for_ws(ws_id, LeadStatus.DRAFTED.value, 12),
            "replies": _sparkline_for_ws(ws_id, LeadStatus.REPLIED.value, 12),
        },
        "funnel": [
            {"label": "Pozyskane", "value": leads_total, "percent": 100.0 if leads_total else 0, "icon": "upload"},
            {"label": "Researched", "value": researched + drafted_total,
             "percent": round((researched + drafted_total) / max(leads_total, 1) * 100, 1), "icon": "search"},
            {"label": "Z draftem", "value": drafted_total,
             "percent": round(drafted_total / max(leads_total, 1) * 100, 1), "icon": "check"},
            {"label": "Wysłane", "value": sent_total_w,
             "percent": round(sent_total_w / max(leads_total, 1) * 100, 1), "icon": "send"},
            {"label": "Odpowiedzieli", "value": replied,
             "percent": round(replied / max(leads_total, 1) * 100, 1), "icon": "message-circle"},
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
        "segments": [{"name": s[0] or "—", "count": int(s[1])} for s in segments],
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

@app.get("/api/leads")
def list_leads(
    limit: int = 50, offset: int = 0,
    segment: str | None = None, status: str | None = None, min_score: float = 0.0,
    cur: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    limit = max(1, min(limit, 200)); offset = max(0, offset)
    with SessionLocal() as session:
        q = select(Lead).where(Lead.workspace_id == cur.workspace_id) \
            .order_by(desc(Lead.score), desc(Lead.created_at))
        if segment: q = q.where(Lead.segment == segment)
        if status: q = q.where(Lead.status == status)
        if min_score > 0: q = q.where(Lead.score >= min_score)

        total = int(session.scalar(select(func.count()).select_from(q.subquery())) or 0)
        rows = session.execute(q.limit(limit).offset(offset)).scalars().all()
        leads = [{
            "id": l.id, "segment": l.segment, "company_name": l.company_name,
            "contact_name": l.contact_name, "email": l.email, "phone": l.phone,
            "website": l.website, "city": l.city, "status": l.status,
            "score": float(l.score) if l.score is not None else None,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        } for l in rows]
    return {"total": total, "items": leads}


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    with SessionLocal() as session:
        lead = session.execute(
            select(Lead).where(Lead.id == lead_id, Lead.workspace_id == cur.workspace_id)
        ).scalar_one_or_none()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead nie istnieje.")
        return {
            "id": lead.id, "segment": lead.segment,
            "company_name": lead.company_name, "contact_name": lead.contact_name,
            "email": lead.email, "phone": lead.phone, "website": lead.website,
            "instagram": lead.instagram, "city": lead.city, "country": lead.country,
            "status": lead.status,
            "score": float(lead.score) if lead.score is not None else None,
            "research_data": lead.research_data, "notes": lead.notes,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        }


# ─── Drafts ──────────────────────────────────────────────────────────────

@app.get("/api/drafts")
def list_drafts(
    status_filter: str | None = "draft", limit: int = 50,
    cur: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        q = select(EmailDraft).where(EmailDraft.workspace_id == cur.workspace_id) \
            .order_by(desc(EmailDraft.created_at)).limit(limit)
        if status_filter: q = q.where(EmailDraft.status == status_filter)
        drafts = session.execute(q).scalars().all()
        return [{
            "id": d.id, "lead_id": d.lead_id,
            "company": d.lead.company_name if d.lead else "(unknown)",
            "subject": d.subject, "snippet1": d.snippet1, "snippet2": d.snippet2,
            "snippet3": d.snippet3, "snippet4": d.snippet4, "snippet5": d.snippet5,
            "full_preview": d.full_preview, "status": d.status,
            "template_variant": d.template_variant, "edited_by_user": d.edited_by_user,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "sent_at": d.sent_at.isoformat() if d.sent_at else None,
        } for d in drafts]


class DraftUpdate(BaseModel):
    subject: str | None = None
    snippet1: str | None = None
    snippet2: str | None = None
    snippet3: str | None = None
    snippet4: str | None = None
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
        if draft.snippet4: parts.extend(["", draft.snippet4])
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
        session.commit()
        _log_event(cur.workspace_id, cur.user_id, "INFO", "gui", "draft_approved",
                   f"Draft #{draft_id} approved")
        return {"ok": True}


@app.post("/api/drafts/{draft_id}/reject")
def reject_draft(draft_id: int, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    with SessionLocal() as session:
        draft = session.execute(
            select(EmailDraft).where(
                EmailDraft.id == draft_id, EmailDraft.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if draft is None: raise HTTPException(status_code=404, detail="Draft nie istnieje.")
        draft.status = DraftStatus.REJECTED.value
        session.commit()
        _log_event(cur.workspace_id, cur.user_id, "INFO", "gui", "draft_rejected",
                   f"Draft #{draft_id} rejected")
        return {"ok": True}


class SendDraftIn(BaseModel):
    campaign_id: int


@app.post("/api/drafts/{draft_id}/send")
def send_draft(draft_id: int, payload: SendDraftIn,
               cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Tworzy SEND_DRAFT job - worker pushuje do Woodpecker, user może wyjść."""
    with SessionLocal() as session:
        draft = session.execute(
            select(EmailDraft).where(
                EmailDraft.id == draft_id, EmailDraft.workspace_id == cur.workspace_id,
            )
        ).scalar_one_or_none()
        if draft is None: raise HTTPException(status_code=404, detail="Draft nie istnieje.")
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
        # Sprawdź czy lead należy do workspace
        lead = session.execute(
            select(Lead).where(Lead.id == payload.lead_id, Lead.workspace_id == cur.workspace_id)
        ).scalar_one_or_none()
        if lead is None: raise HTTPException(status_code=404, detail="Lead nie istnieje w Twoim workspace.")
        job = create_job(
            session, job_type=JobType.GENERATE_DRAFT,
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            payload={
                "lead_id": payload.lead_id,
                "provider": payload.provider, "model": payload.model,
            },
        )
    return {"ok": True, "job_id": job.id}


# ─── Discovery + research jako jobs ─────────────────────────────────────

class DiscoverIn(BaseModel):
    query: str
    sources: list[str]
    max_per_source: int = 20
    segment: str = "inne"
    location: str | None = None
    custom_description: str | None = None
    use_relevance_filter: bool = True
    relevance_threshold: int = 6
    auto_research: bool = True
    auto_draft_threshold: int | None = 7


@app.post("/api/discovery/search")
def discovery_search(payload: DiscoverIn, cur: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Tworzy DISCOVERY_PIPELINE job - worker zrobi: znajdź -> filter -> research -> draft.

    Zwraca job_id natychmiast. Frontend polluje /api/jobs/{id} dla progressu.
    User może wylogować się - worker leci dalej.
    """
    with SessionLocal() as session:
        job = create_job(
            session, job_type=JobType.DISCOVERY_PIPELINE,
            workspace_id=cur.workspace_id, user_id=cur.user_id,
            payload=payload.model_dump(),
        )
    return {"ok": True, "job_id": job.id}


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


# ─── Jobs polling ────────────────────────────────────────────────────────

@app.get("/api/jobs")
def list_jobs(
    status: str | None = None, limit: int = 30,
    cur: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with SessionLocal() as session:
        q = select(Job).where(Job.workspace_id == cur.workspace_id) \
            .order_by(desc(Job.created_at)).limit(limit)
        if status: q = q.where(Job.status == status)
        jobs = session.execute(q).scalars().all()
        return [serialize_job(j) for j in jobs]


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
