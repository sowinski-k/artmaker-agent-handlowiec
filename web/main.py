"""Ecombinat FastAPI backend.

JSON API serwujący agent/ modules dla Next.js frontend'u. Każdy endpoint
zwraca prosty JSON; auth przez cookie (signed session) - bez Clerka na MVP.

Endpointy:
  POST /api/auth/login           {password} -> set cookie
  POST /api/auth/logout          -> clear cookie
  GET  /api/auth/me              -> current user status
  GET  /api/dashboard            -> dashboard stats (counts, funnel)
  GET  /api/leads                -> list leads (paginated)
  GET  /api/leads/{id}           -> single lead details
  GET  /api/drafts               -> list drafts
  POST /api/drafts/{id}/approve  -> approve
  POST /api/drafts/{id}/reject   -> reject
  POST /api/drafts/{id}/send     -> push to Woodpecker
  POST /api/discovery/search     -> {segment, location, sources} -> results
  POST /api/research             -> {url} -> Lead row
  GET  /api/events?limit=N       -> recent Event rows for activity feed

W tym commit'cie wszystkie endpointy zwracaja mock data zeby frontend mial
co rysowac. Real DB integration w nastepnym commit.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow imports from project root (core/, agent/)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel

# ─── Config ──────────────────────────────────────────────────────────────

APP_PASSWORD = (os.getenv("APP_PASSWORD") or "").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET") or "ecombinat-dev-secret-change-in-prod"
COOKIE_NAME = "ecombinat_session"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 dni

_origins_env = (os.getenv("FRONTEND_ORIGINS") or "http://localhost:3000").strip()
# Special value "*" -> wildcard. Inaczej comma-separated lista origin'ow.
if _origins_env == "*":
    ALLOWED_ORIGINS = ["*"]
else:
    ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]
# UWAGA: gdy allow_credentials=True, browsery odrzucaja allow_origins=["*"].
# W production zawsze podaj konkretny URL frontendu w FRONTEND_ORIGINS.

serializer = URLSafeSerializer(SESSION_SECRET, salt="ecombinat-session-v1")


# ─── App setup ──────────────────────────────────────────────────────────

app = FastAPI(title="Ecombinat API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth helpers ───────────────────────────────────────────────────────

def _make_token() -> str:
    """Token sesji (signed JWT-like blob). Działa zarówno jako Bearer token
    w Authorization header (preferred, cross-origin friendly) jak i jako
    httponly cookie (fallback dla SSR)."""
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
    """Pobierz token: najpierw z Authorization: Bearer ..., potem z cookie."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def require_auth(request: Request) -> None:
    """FastAPI dependency: rzuca 401 jeśli sesja niewazna."""
    if not APP_PASSWORD:
        return  # No password set = open access (lokalny dev)
    if not _verify_token(_extract_token(request)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Brak autoryzacji - zaloguj się.",
        )


# ─── Schemas ────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    password: str


class StatusOut(BaseModel):
    authed: bool
    app_name: str = "Ecombinat"


class LoginOut(BaseModel):
    authed: bool
    token: str  # Bearer token - frontend zapisuje w localStorage
    app_name: str = "Ecombinat"


# ─── Routes ─────────────────────────────────────────────────────────────

@app.get("/")
def root() -> dict[str, Any]:
    """Healthcheck + version info."""
    return {
        "app": "ecombinat-api",
        "version": "0.1.0",
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(payload: LoginIn, response: Response) -> LoginOut:
    if APP_PASSWORD and payload.password != APP_PASSWORD:
        raise HTTPException(status_code=401, detail="Złe hasło.")
    token = _make_token()
    # Ustaw też cookie jako fallback dla SSR (jeśli kiedyś frontend będzie
    # robił auth-aware SSR). Cross-origin -> samesite=none + secure=true.
    is_prod = os.getenv("RAILWAY_ENVIRONMENT") is not None
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="none" if is_prod else "lax",
        secure=is_prod,
    )
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


# ─── Dashboard (mock data na ten commit) ────────────────────────────────

@app.get("/api/dashboard", dependencies=[Depends(require_auth)])
def get_dashboard() -> dict[str, Any]:
    """Główne metryki + funnel + activity. Mock data; real DB w commit 2."""
    return {
        "stats": {
            "leads_total": 142,
            "leads_hot": 23,
            "drafts_pending": 8,
            "avg_score": 6.8,
            "researched": 89,
            "sent_today": 12,
            "replied": 7,
            "reply_rate": 5.8,
            "bounced": 2,
        },
        "sparklines": {
            "leads": [3, 5, 4, 6, 8, 9, 12, 14, 18, 22, 28, 30],
            "drafts": [0, 0, 2, 3, 5, 7, 8, 10, 12, 14, 14, 16],
            "replies": [0, 1, 1, 2, 2, 3, 3, 4, 5, 6, 7, 7],
        },
        "funnel": [
            {"label": "Pozyskane", "value": 142, "percent": 100.0, "icon": "upload"},
            {"label": "Researched", "value": 89, "percent": 62.7, "icon": "search"},
            {"label": "Z draftem", "value": 35, "percent": 24.6, "icon": "check"},
            {"label": "Wysłane", "value": 19, "percent": 13.4, "icon": "send"},
            {"label": "Odpowiedzieli", "value": 7, "percent": 4.9, "icon": "message-circle"},
        ],
        "system": [
            {"label": "Agent (STOP.txt)", "value": "running", "status": "ok"},
            {"label": "DRY_RUN", "value": "false", "status": "ok"},
            {"label": "Anthropic key", "value": "OK", "status": "ok"},
            {"label": "Gemini key", "value": "OK", "status": "ok"},
            {"label": "Apify token", "value": "brak", "status": "warn"},
            {"label": "Google Places", "value": "OK", "status": "ok"},
        ],
        "segments": [
            {"name": "sklep_papierniczy", "count": 47},
            {"name": "sklep_plastyczny", "count": 38},
            {"name": "paint_and_sip", "count": 21},
            {"name": "warsztaty_dzieci", "count": 18},
            {"name": "szkola_artystyczna", "count": 12},
            {"name": "marka_wlasna", "count": 6},
        ],
    }


@app.get("/api/events", dependencies=[Depends(require_auth)])
def get_events(limit: int = 8) -> list[dict[str, Any]]:
    return [
        {"icon": "search", "accent": True,
         "text": "<strong>research</strong> · Lead #142 Tania-Paka.pl researched, score 8/10",
         "time": "2m"},
        {"icon": "wand", "accent": True,
         "text": "<strong>generate</strong> · Draft #38 wygenerowany dla Lead #141",
         "time": "5m"},
        {"icon": "send", "accent": False,
         "text": "<strong>push</strong> · Draft #36 wysłany do Woodpecker (prospect_id=8821)",
         "time": "12m"},
        {"icon": "upload", "accent": True,
         "text": "<strong>discovery</strong> · 23 nowych firm znalezionych dla 'sklep papierniczy Łask'",
         "time": "1h"},
        {"icon": "refresh", "accent": False,
         "text": "<strong>poll</strong> · Lead #128 status zmieniony: SENT → REPLIED",
         "time": "3h"},
    ][:limit]


@app.get("/api/leads", dependencies=[Depends(require_auth)])
def list_leads(limit: int = 50) -> list[dict[str, Any]]:
    return [
        {"id": 142, "company": "Tania-Paka.pl", "segment": "sklep_papierniczy",
         "city": "Łask", "score": 8.0, "status": "researched", "email": "info@tania-paka.pl"},
        {"id": 141, "company": "Good Time Art Studio", "segment": "paint_and_sip",
         "city": "Warszawa", "score": 9.0, "status": "drafted", "email": "kontakt@gtas.pl"},
    ]


@app.get("/api/drafts", dependencies=[Depends(require_auth)])
def list_drafts(limit: int = 50) -> list[dict[str, Any]]:
    return [
        {"id": 38, "lead_id": 141, "company": "Good Time Art Studio",
         "subject": "Pytanie o płótna do warsztatów?", "status": "draft",
         "offer_track": "b2b_panel", "edited": False},
    ]
