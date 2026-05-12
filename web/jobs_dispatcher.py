"""Job dispatcher - tworzy rekordy Job w bazie, worker proces ich szuka i wykonuje.

To pozwala na 'fire and forget' z UI: user klika przycisk, dostaje natychmiast
job_id, może się wylogować. Worker process (osobny Railway service) wykonuje
job w tle, nawet jeśli user zamknął browser. Frontend polluje /api/jobs/{id}.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.db import Job, JobStatus, JobType


def create_job(
    session: Session,
    *,
    job_type: JobType,
    workspace_id: int,
    user_id: int | None,
    payload: dict[str, Any],
    total: int = 0,
) -> Job:
    """Tworzy job pending, worker go zobaczy w ciągu max 5 sekund (polling)."""
    job = Job(
        workspace_id=workspace_id,
        user_id=user_id,
        type=job_type.value,
        status=JobStatus.PENDING.value,
        payload=payload,
        progress=0,
        total=total,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def find_active_job(
    session: Session,
    workspace_id: int,
    *,
    job_types: list[str] | None = None,
) -> Job | None:
    """Zwraca pierwszy aktywny (pending lub running) job w workspace dla
    danego typu (lub wszystkich gdy job_types=None). Uzywane do guarda
    przeciw double-job tego samego typu.
    """
    from sqlalchemy import select as _sel
    q = _sel(Job).where(
        Job.workspace_id == workspace_id,
        Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
    )
    if job_types:
        q = q.where(Job.type.in_(job_types))
    q = q.order_by(Job.created_at.desc()).limit(1)
    return session.execute(q).scalar_one_or_none()


def serialize_job(job: Job, *, lite: bool = False) -> dict[str, Any]:
    """JSON-safe reprezentacja joba dla frontu.

    lite=True: pomija payload + result (moga byc duze - 100 URLi, JSON z research).
    Uzywane przez listingi (auto-refresh co 5s, nie potrzebujemy detalu).
    """
    out: dict[str, Any] = {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "progress": int(job.progress or 0),
        "total": int(job.total or 0),
        "retries": int(job.retries or 0),
        "last_error": job.last_error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
    if not lite:
        out["payload"] = job.payload
        out["result"] = job.result
    return out
