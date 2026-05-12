"""Multi-tenant auth: bcrypt password hashing + signed tokens (itsdangerous).

Token payload: {user_id, workspace_id, iat}. Frontend trzyma token w
localStorage (Authorization: Bearer) i cookie (fallback dla SSR).

Każdy uwierzytelniony endpoint dostaje CurrentUser przez get_current_user
dependency - z workspace_id potrzebnym do tenant isolation w queries.
"""
from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import bcrypt
from fastapi import Cookie, Header, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import (
    SessionLocal,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)


# ─── Config ──────────────────────────────────────────────────────────────

SESSION_SECRET = os.getenv("SESSION_SECRET") or "ecombinat-dev-secret-change-in-prod"
TOKEN_SALT = "ecombinat-auth-v2"
COOKIE_NAME = "ecombinat_session"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 dni

_serializer = URLSafeSerializer(SESSION_SECRET, salt=TOKEN_SALT)

# Wymagania hasła - bezpieczne minimum (zmienialne przez env)
PASSWORD_MIN_LEN = int(os.getenv("PASSWORD_MIN_LEN") or 8)


# ─── Password hashing ────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """bcrypt z workfactor 12 (~250ms na nowoczesnym CPU)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def validate_password(plain: str) -> tuple[bool, str]:
    """Sprawdza złożoność. Zwraca (ok, error_message)."""
    if len(plain) < PASSWORD_MIN_LEN:
        return False, f"Hasło musi mieć co najmniej {PASSWORD_MIN_LEN} znaków."
    if plain.lower() == plain or plain.upper() == plain:
        return False, "Hasło musi zawierać małą i wielką literę."
    if not re.search(r"\d", plain):
        return False, "Hasło musi zawierać cyfrę."
    return True, ""


def validate_email(email: str) -> bool:
    """Prosty regex - production-ready validation robi się przez wysłanie verify maila."""
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email.strip()))


# ─── Token signing ───────────────────────────────────────────────────────

def make_token(user_id: int, workspace_id: int) -> str:
    """Signed session token. Nie można sfałszować bez SESSION_SECRET."""
    return _serializer.dumps({
        "user_id": user_id,
        "workspace_id": workspace_id,
        "iat": datetime.now(timezone.utc).isoformat(),
        "jti": secrets.token_urlsafe(8),  # unique per token (audit)
    })


def verify_token(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        data = _serializer.loads(token)
        if not isinstance(data, dict): return None
        if "user_id" not in data or "workspace_id" not in data: return None
        return data
    except BadSignature:
        return None


# ─── CurrentUser dependency ──────────────────────────────────────────────

@dataclass
class CurrentUser:
    user_id: int
    workspace_id: int
    email: str
    name: str | None
    is_admin: bool
    workspace_name: str
    workspace_plan: str


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def get_current_user(request: Request) -> CurrentUser:
    """FastAPI dependency. Rzuca 401 jeśli brak tokenu / niepoprawny."""
    token = _extract_token(request)
    data = verify_token(token)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Brak autoryzacji - zaloguj się.",
        )
    with SessionLocal() as session:
        user = session.get(User, data["user_id"])
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Konto nieaktywne.")
        ws = session.get(Workspace, data["workspace_id"])
        if ws is None:
            raise HTTPException(status_code=401, detail="Workspace nie istnieje.")
        # Verify membership (defensywnie - nawet jeśli token dobry, sprawdź żywą relację)
        member = session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.workspace_id == ws.id,
            )
        ).scalar_one_or_none()
        if member is None and not user.is_admin:
            raise HTTPException(status_code=403, detail="Brak dostępu do workspace.")
        return CurrentUser(
            user_id=user.id,
            workspace_id=ws.id,
            email=user.email,
            name=user.name,
            is_admin=user.is_admin,
            workspace_name=ws.name,
            workspace_plan=ws.plan,
        )


# ─── Registration helper ─────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Prosty slug dla workspace.slug - lowercase + dashes + unique suffix."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text[:48] or "workspace"


def register_user(
    session: Session,
    email: str,
    password: str,
    name: str | None = None,
    workspace_name: str | None = None,
) -> tuple[User, Workspace]:
    """Tworzy User + Workspace + WorkspaceMember(owner) w jednej transakcji.

    Returns (user, workspace). Raise HTTPException przy konfliktach.
    """
    email = email.strip().lower()
    if not validate_email(email):
        raise HTTPException(status_code=400, detail="Nieprawidłowy email.")
    ok, err = validate_password(password)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email już zarejestrowany.")

    user = User(
        email=email,
        password_hash=hash_password(password),
        name=name or email.split("@")[0],
    )
    session.add(user)
    session.flush()

    # Workspace name + unique slug
    ws_name = (workspace_name or f"{user.name or 'Workspace'}").strip()[:255] or "Workspace"
    base_slug = slugify(ws_name)
    slug = base_slug
    n = 1
    while session.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none():
        n += 1
        slug = f"{base_slug}-{n}"

    workspace = Workspace(
        name=ws_name,
        slug=slug,
        owner_user_id=user.id,
        plan="free",
        monthly_credits=100,
    )
    session.add(workspace)
    session.flush()

    session.add(WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER.value,
    ))
    session.commit()
    return user, workspace
