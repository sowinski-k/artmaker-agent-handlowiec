"""Background worker - polluje Job table i wykonuje pending jobs.

Osobny Railway service. Działa 24/7 niezależnie od request HTTP / browsera
użytkownika. User może wylogować się, zamknąć komputer - jobs lecą dalej.

Polling co 5s. Single-worker setup (jeden Railway replica) na MVP - retry
przy crashu wbudowane. Scale do multi-worker (SELECT FOR UPDATE SKIP LOCKED
w Postgres) gdy będzie potrzeba.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow imports z root projektu
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import (
    Event,
    Job,
    JobStatus,
    JobType,
    SessionLocal,
    init_db,
)

POLL_INTERVAL_S = float(os.getenv("WORKER_POLL_INTERVAL", "5"))
JOB_TIMEOUT_S = float(os.getenv("JOB_TIMEOUT", "1800"))  # 30 min hard limit
MAX_RETRIES = int(os.getenv("JOB_MAX_RETRIES", "3"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s worker: %(message)s",
)
log = logging.getLogger("worker")

_shutdown = False


def _handle_shutdown(signum, frame):
    global _shutdown
    log.info(f"Received signal {signum}, draining and shutting down...")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)


# ─── Job handlers ────────────────────────────────────────────────────────

def _log_event(session: Session, workspace_id: int, level: str, type_: str, msg: str) -> None:
    session.add(Event(
        workspace_id=workspace_id, type=type_, level=level,
        source="worker", message=msg[:1000],
    ))


def handle_discovery_pipeline(session: Session, job: Job) -> dict:
    """Pełny pipeline discovery -> research -> auto-draft.

    Payload:
        query: str
        sources: list[str] ('apify', 'google_places', ...)
        max_per_source: int
        segment: str
        location: str | None
        custom_description: str | None
        relevance_threshold: int (default 6)
        auto_research: bool
        auto_draft_threshold: int | None (np. 7 = generuj draft jeśli score >= 7)
    """
    from agent.discovery import (
        ApifyAllegroSource, ApifyLinkedInSource, ApifySource,
        GooglePlacesSource, run_search, score_relevance_batch,
    )
    from agent.research import research_and_save
    from agent.generate import generate_draft_for_lead

    p = job.payload
    src_classes = {
        "apify": ApifySource, "google_places": GooglePlacesSource,
        "apify_allegro": ApifyAllegroSource, "apify_linkedin": ApifyLinkedInSource,
    }
    sources = []
    for s in p.get("sources", []):
        cls = src_classes.get(s)
        if cls is None: continue
        inst = cls()
        if inst.available():
            sources.append(inst)
    if not sources:
        raise RuntimeError("Żadne źródło nie jest dostępne (brak kluczy API).")

    log.info(f"Job #{job.id} discovery: query={p['query']!r} sources={p['sources']}")
    places, diag = run_search(
        sources,
        query=p["query"],
        max_results_per_source=int(p.get("max_per_source", 20)),
    )

    threshold = int(p.get("relevance_threshold", 6))
    targets: list = []
    if p.get("use_relevance_filter", True) and places:
        items, _ = score_relevance_batch(
            places, segment=p.get("segment", "inne"),
            city=p.get("location"),
            custom_description=p.get("custom_description"),
        )
        for it in items:
            if it.score >= threshold and 0 <= it.idx < len(places):
                place = places[it.idx]
                if place.website and place.existing_lead_id is None:
                    targets.append(place)
    else:
        targets = [pl for pl in places if pl.website and pl.existing_lead_id is None]

    job.total = len(targets)
    job.progress = 0
    session.commit()
    log.info(f"Job #{job.id}: {len(targets)} fresh targets to research")

    if not p.get("auto_research", True):
        # Tylko discovery + scoring, bez research
        return {
            "places_found": len(places),
            "targets_matching": len(targets),
            "researched": 0, "drafted": 0, "duplicates": 0, "failed": 0,
            "diagnostics": [d.model_dump() for d in diag],
        }

    auto_draft_th = p.get("auto_draft_threshold")
    researched, drafted, dups, failed = 0, 0, 0, 0

    for i, place in enumerate(targets, start=1):
        if _shutdown: break
        try:
            lead_id, result, was_researched = research_and_save(
                place.website,
                segment_hint=p.get("segment"),
                city_hint=p.get("location"),
                workspace_id=job.workspace_id,
            )
            if not was_researched:
                dups += 1
            else:
                researched += 1
                if auto_draft_th is not None and result.score.total >= int(auto_draft_th):
                    try:
                        generate_draft_for_lead(lead_id, workspace_id=job.workspace_id)
                        drafted += 1
                    except Exception as exc:
                        log.warning(f"Job #{job.id} draft for lead {lead_id} failed: {exc}")
        except Exception as exc:
            failed += 1
            log.warning(f"Job #{job.id} research for {place.website} failed: {exc}")
        job.progress = i
        session.commit()

    return {
        "places_found": len(places),
        "targets_matching": len(targets),
        "researched": researched,
        "drafted": drafted,
        "duplicates": dups,
        "failed": failed,
    }


def handle_research_lead(session: Session, job: Job) -> dict:
    from agent.research import research_and_save
    p = job.payload
    lead_id, result, was_researched = research_and_save(
        p["url"],
        segment_hint=p.get("segment_hint"),
        city_hint=p.get("city_hint"),
        force_refresh=bool(p.get("force_refresh")),
        workspace_id=job.workspace_id,
    )
    return {
        "lead_id": lead_id, "was_researched": was_researched,
        "score": result.score.total if result else None,
        "company": result.company_name if result else None,
    }


def handle_generate_draft(session: Session, job: Job) -> dict:
    from agent.generate import generate_draft_for_lead
    p = job.payload
    draft_id = generate_draft_for_lead(
        p["lead_id"],
        provider=p.get("provider"), model=p.get("model"),
        workspace_id=job.workspace_id,
    )
    return {"draft_id": draft_id}


def handle_bulk_generate_drafts(session: Session, job: Job) -> dict:
    from agent.generate import generate_all_researched
    p = job.payload
    made, failed = generate_all_researched(
        provider=p.get("provider"), model=p.get("model"),
        min_score=float(p.get("min_score", 0)),
        workspace_id=job.workspace_id,
    )
    return {"made": made, "failed": failed}


def handle_send_draft(session: Session, job: Job) -> dict:
    from agent.push_to_sender import push_draft
    p = job.payload
    prospect_id = push_draft(p["draft_id"], p["campaign_id"])
    return {"prospect_id": prospect_id}


def handle_poll_woodpecker(session: Session, job: Job) -> dict:
    from scripts.poll_woodpecker import poll_statuses
    counts = poll_statuses(max_leads=int(job.payload.get("max", 200)))
    return counts


JOB_HANDLERS = {
    JobType.DISCOVERY_PIPELINE.value: handle_discovery_pipeline,
    JobType.RESEARCH_LEAD.value: handle_research_lead,
    JobType.GENERATE_DRAFT.value: handle_generate_draft,
    JobType.BULK_GENERATE_DRAFTS.value: handle_bulk_generate_drafts,
    JobType.SEND_DRAFT.value: handle_send_draft,
    JobType.POLL_WOODPECKER.value: handle_poll_woodpecker,
}


# ─── Worker loop ────────────────────────────────────────────────────────

def claim_next_job(session: Session) -> Job | None:
    """Wybiera najstarsze pending job i flaguje running. Atomically.

    Uwaga: pojedynczy worker na MVP - bez SELECT FOR UPDATE. Jeśli skalujesz
    do wielu worker'ów, dorzuć `.with_for_update(skip_locked=True)` (Postgres).
    """
    job = session.execute(
        select(Job)
        .where(Job.status == JobStatus.PENDING.value)
        .order_by(Job.created_at)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = JobStatus.RUNNING.value
    job.started_at = datetime.now(timezone.utc)
    session.commit()
    return job


def execute_job(job_id: int) -> None:
    """Wykonaj pojedynczy job - własna sesja, własna transakcja."""
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None:
            log.error(f"Job #{job_id} zniknął z bazy")
            return
        handler = JOB_HANDLERS.get(job.type)
        if handler is None:
            job.status = JobStatus.FAILED.value
            job.last_error = f"Unknown job type: {job.type}"
            job.completed_at = datetime.now(timezone.utc)
            _log_event(session, job.workspace_id, "ERROR", "job_failed",
                       f"Job #{job.id} unknown type {job.type}")
            session.commit()
            return

        try:
            result = handler(session, job)
            job.result = result
            job.status = JobStatus.DONE.value
            job.completed_at = datetime.now(timezone.utc)
            _log_event(session, job.workspace_id, "INFO", "job_done",
                       f"Job #{job.id} ({job.type}) done")
            session.commit()
            log.info(f"Job #{job.id} DONE - {result}")
        except Exception as exc:
            log.exception(f"Job #{job.id} failed: {exc}")
            job.retries = (job.retries or 0) + 1
            job.last_error = str(exc)[:1000]
            if job.retries >= MAX_RETRIES:
                job.status = JobStatus.FAILED.value
                job.completed_at = datetime.now(timezone.utc)
                _log_event(session, job.workspace_id, "ERROR", "job_failed",
                           f"Job #{job.id} ({job.type}) failed after {MAX_RETRIES} retries: {exc}")
            else:
                # Z powrotem do pending, spróbujemy znowu za poll-interval
                job.status = JobStatus.PENDING.value
                job.started_at = None
                _log_event(session, job.workspace_id, "WARNING", "job_retry",
                           f"Job #{job.id} retry {job.retries}/{MAX_RETRIES}: {exc}")
            session.commit()


def loop_forever() -> None:
    log.info(f"Worker starting (poll interval {POLL_INTERVAL_S}s, max retries {MAX_RETRIES})")
    init_db()
    while not _shutdown:
        try:
            with SessionLocal() as session:
                job = claim_next_job(session)
            if job is None:
                time.sleep(POLL_INTERVAL_S)
                continue
            log.info(f"Job #{job.id} CLAIMED type={job.type} ws={job.workspace_id}")
            execute_job(job.id)
        except Exception as exc:
            log.exception(f"Worker loop error: {exc}")
            time.sleep(POLL_INTERVAL_S)
    log.info("Worker shutdown clean")


if __name__ == "__main__":
    loop_forever()
