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

from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import Session

from core.db import (
    Event,
    Job,
    JobStatus,
    JobType,
    Lead,
    PatrolSchedule,
    SessionLocal,
    init_db,
)

POLL_INTERVAL_S = float(os.getenv("WORKER_POLL_INTERVAL", "5"))
JOB_TIMEOUT_S = float(os.getenv("JOB_TIMEOUT", "1800"))  # 30 min hard limit
MAX_RETRIES = int(os.getenv("JOB_MAX_RETRIES", "3"))
PATROL_TICK_S = float(os.getenv("PATROL_TICK_INTERVAL", "60"))  # check patrols co 60s
HEARTBEAT_S = float(os.getenv("WORKER_HEARTBEAT_INTERVAL", "60"))  # heartbeat co 60s
# Kosz: leady z deleted_at starszym niz RECYCLE_BIN_DAYS zostaja hard-deleted
# (cascade na drafty). Tick co PURGE_TICK_S - default 1h zeby nie spamowac DB.
RECYCLE_BIN_DAYS = int(os.getenv("RECYCLE_BIN_DAYS", "7"))
PURGE_TICK_S = float(os.getenv("PURGE_TICK_INTERVAL", "3600"))  # co 1h

from core.observability import init_sentry
init_sentry("worker")

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

def _log_event(
    session: Session, workspace_id: int, level: str, type_: str, msg: str,
    lead_id: int | None = None,
) -> None:
    session.add(Event(
        workspace_id=workspace_id, type=type_, level=level,
        source="worker", message=msg[:1000], lead_id=lead_id,
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
        max_results_per_source=int(p.get("max_per_source", 50)),
        workspace_id=job.workspace_id,
        city_filter=p.get("location") if p.get("apply_city_filter", True) else None,
        source_queries=p.get("source_queries"),
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
    recent: list[dict] = []  # Live ticker - frontend wyswietla na biezaco

    for i, place in enumerate(targets, start=1):
        if _shutdown: break
        if _is_cancelled(session, job.id):
            log.info(f"Job #{job.id} cancelled by user at {i}/{len(targets)}")
            break
        entry: dict = {"url": place.website, "name": place.name or place.website}
        try:
            lead_id, result, was_researched = research_and_save(
                place.website,
                segment_hint=p.get("segment"),
                city_hint=p.get("location"),
                workspace_id=job.workspace_id,
            )
            if not was_researched:
                dups += 1
                entry.update({"status": "duplicate", "lead_id": lead_id})
            else:
                researched += 1
                entry.update({
                    "status": "researched",
                    "lead_id": lead_id,
                    "name": result.company_name if result else entry["name"],
                    "score": result.score.total if result else None,
                })
                if auto_draft_th is not None and result.score.total >= int(auto_draft_th):
                    try:
                        generate_draft_for_lead(lead_id, workspace_id=job.workspace_id)
                        drafted += 1
                        entry["drafted"] = True
                    except Exception as exc:
                        log.warning(f"Job #{job.id} draft for lead {lead_id} failed: {exc}")
                        entry["drafted"] = False
        except Exception as exc:
            failed += 1
            log.warning(f"Job #{job.id} research for {place.website} failed: {exc}")
            entry.update({"status": "failed", "error": str(exc)[:120]})
        # Trzymamy ostatnich 15 - wystarcza dla UI, lekkie payload.
        recent.append(entry)
        recent = recent[-15:]
        job.progress = i
        job.result = {
            "places_found": len(places), "targets_matching": len(targets),
            "researched": researched, "drafted": drafted,
            "duplicates": dups, "failed": failed,
            "recent": recent,
        }
        session.commit()

    return {
        "places_found": len(places),
        "targets_matching": len(targets),
        "researched": researched,
        "drafted": drafted,
        "duplicates": dups,
        "failed": failed,
        "recent": recent,
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


def handle_bulk_research_leads(session: Session, job: Job) -> dict:
    """Praca ręczna - user wybrał N stron WWW, researchujemy każdą.

    Payload:
        urls: list[str]
        segment_hint: str | None
        city_hint: str | None
        auto_draft_threshold: int | None
    """
    from agent.research import research_and_save
    from agent.generate import generate_draft_for_lead

    p = job.payload
    urls = list(p.get("urls") or [])
    job.total = len(urls)
    job.progress = 0
    session.commit()

    researched, dups, failed, drafted = 0, 0, 0, 0
    auto_draft_th = p.get("auto_draft_threshold")
    recent: list[dict] = []  # Live ticker

    for i, url in enumerate(urls, start=1):
        if _shutdown: break
        if _is_cancelled(session, job.id):
            log.info(f"Job #{job.id} cancelled by user at {i}/{len(urls)}")
            break
        entry: dict = {"url": url, "name": url}
        try:
            lead_id, result, was = research_and_save(
                url,
                segment_hint=p.get("segment_hint"),
                city_hint=p.get("city_hint"),
                workspace_id=job.workspace_id,
                force_refresh=bool(p.get("force_refresh", False)),
            )
            if not was:
                dups += 1
                entry.update({"status": "duplicate", "lead_id": lead_id})
            else:
                researched += 1
                entry.update({
                    "status": "researched",
                    "lead_id": lead_id,
                    "name": result.company_name if result else url,
                    "score": result.score.total if result else None,
                })
                if auto_draft_th is not None and result and result.score.total >= int(auto_draft_th):
                    try:
                        generate_draft_for_lead(lead_id, workspace_id=job.workspace_id)
                        drafted += 1
                        entry["drafted"] = True
                    except Exception as exc:
                        log.warning(f"Job #{job.id} draft for lead {lead_id} failed: {exc}")
                        entry["drafted"] = False
        except Exception as exc:
            failed += 1
            log.warning(f"Job #{job.id} research {url} failed: {exc}")
            entry.update({"status": "failed", "error": str(exc)[:120]})
        recent.append(entry)
        recent = recent[-15:]
        job.progress = i
        job.result = {
            "total": len(urls), "researched": researched,
            "duplicates": dups, "failed": failed, "drafted": drafted,
            "recent": recent,
        }
        session.commit()

    return {
        "total": len(urls), "researched": researched,
        "duplicates": dups, "failed": failed, "drafted": drafted,
        "recent": recent,
    }


def handle_enrich_lead(session: Session, job: Job) -> dict:
    """Enrich pojedynczego leada - scrape homepage po email/phone.

    Payload:
        lead_id: int
    """
    from agent.contact_finder import enrich_lead_in_db
    p = job.payload
    result = enrich_lead_in_db(int(p["lead_id"]), workspace_id=job.workspace_id)
    return {
        "lead_id": int(p["lead_id"]),
        "email": result.email,
        "phone": result.phone,
        "source": result.source,
        "pages_checked": result.pages_checked,
        "duration_s": result.duration_s,
    }


def handle_bulk_enrich_leads(session: Session, job: Job) -> dict:
    """Bulk enrich - znajdz wszystkie leady ws bez kontaktu i probuj scrape.

    Payload:
        limit: int (default 100, max 1000)
        include_dead_end: bool (default False - pomijaj juz oznaczone)
    """
    from agent.contact_finder import enrich_lead_in_db, find_leads_to_enrich
    p = job.payload or {}
    lead_ids = find_leads_to_enrich(
        job.workspace_id,
        limit=int(p.get("limit", 100)),
        include_dead_end=bool(p.get("include_dead_end", False)),
    )
    job.total = len(lead_ids)
    job.progress = 0
    session.commit()
    log.info(f"Job #{job.id} bulk_enrich: {len(lead_ids)} leadow do sprawdzenia")

    enriched, dead_ends, failed = 0, 0, 0
    for i, lid in enumerate(lead_ids, start=1):
        if _shutdown: break
        if _is_cancelled(session, job.id):
            log.info(f"Job #{job.id} cancelled by user at {i}/{len(lead_ids)}")
            break
        try:
            res = enrich_lead_in_db(lid, workspace_id=job.workspace_id)
            if res.email or res.phone:
                enriched += 1
            else:
                dead_ends += 1
        except Exception as exc:
            failed += 1
            log.warning(f"Job #{job.id} enrich lead #{lid} failed: {exc}")
        job.progress = i
        session.commit()

    return {
        "checked": len(lead_ids), "enriched": enriched,
        "dead_ends": dead_ends, "failed": failed,
    }


def handle_generate_draft(session: Session, job: Job) -> dict:
    from agent.generate import generate_draft_for_lead
    p = job.payload
    lead_id = p["lead_id"]
    _log_event(session, job.workspace_id, "INFO", "draft.generating",
               f"Generuje draft dla lead #{lead_id}...", lead_id=lead_id)
    session.commit()  # widoczne w timeline od razu
    draft_id = generate_draft_for_lead(
        lead_id,
        provider=p.get("provider"), model=p.get("model"),
        workspace_id=job.workspace_id,
    )
    _log_event(session, job.workspace_id, "INFO", "draft.generated",
               f"Draft #{draft_id} wygenerowany.", lead_id=lead_id)
    return {"draft_id": draft_id, "lead_id": lead_id}


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
    prospect_id = push_draft(
        p["draft_id"], p["campaign_id"], workspace_id=job.workspace_id,
    )
    return {"prospect_id": prospect_id}


def handle_poll_woodpecker(session: Session, job: Job) -> dict:
    from scripts.poll_woodpecker import poll_statuses
    counts = poll_statuses(max_leads=int(job.payload.get("max", 200)))
    return counts


def handle_autonomous_discovery(session: Session, job: Job) -> dict:
    """Faza 4: autonomous discovery agent.

    Iteruje po top miastach PL (z core.cities_pl), w kazdym wykonuje
    discovery z cache + relevance + auto-research. Stopuje gdy osiagnie
    target_new_leads ALBO max_cost_usd ALBO max_cities_to_try.

    Progress: job.progress = liczba juz zapisanych nowych leadow,
    job.total = target_new_leads. Frontend pollami /api/jobs/{id}
    widzi live progress.

    Cost tracking: szacujemy $0.04 per city Google Places (60 results)
    + $0.005 per LLM relevance call. Real cost moze byc rozne.
    """
    from agent.discovery import (
        ApifyAllegroSource, ApifyLinkedInSource, ApifySource,
        GooglePlacesSource, run_search, score_relevance_batch,
    )
    from agent.research import research_and_save
    from core.cities_pl import get_top_cities, cities_in_voivodeship
    from core.urls import normalize_url

    p = job.payload
    target = int(p.get("target_new_leads", 50))
    max_cost = float(p.get("max_cost_usd", 5.0))
    threshold = int(p.get("relevance_threshold", 6))
    auto_draft_th = p.get("auto_draft_threshold")
    max_cities = int(p.get("max_cities_to_try", 50))
    voiv_filter = p.get("voivodeship_filter")
    custom_desc = p.get("custom_description")
    sources_list = p.get("sources", [])

    # Multi-segment: lista segmentow. Backward compat - jak brak segments
    # bierzemy `segment` jako single-item list.
    segments_list = p.get("segments") or ([p.get("segment", "inne")] if p.get("segment") else ["inne"])

    # Wybierz miasta (raz, ten sam zbior dla wszystkich segmentow)
    if voiv_filter:
        cities_list = cities_in_voivodeship(voiv_filter)
    else:
        cities_list = get_top_cities(max_cities)
    cities_list = cities_list[:max_cities]

    # Build full work-queue: dla kazdego segmentu kazde miasto.
    # Iterujemy [(seg, city), ...] - zawsze sekwencyjnie wewnatrz tego joba
    # (wiec worker pool nie pomieszal segmentow per miasto).
    work_queue: list[tuple[str, dict]] = [
        (seg, city) for seg in segments_list for city in cities_list
    ]

    # Setup sources
    src_classes = {
        "apify": ApifySource, "google_places": GooglePlacesSource,
        "apify_allegro": ApifyAllegroSource, "apify_linkedin": ApifyLinkedInSource,
    }
    sources = []
    for s in sources_list:
        cls = src_classes.get(s)
        if cls is None:
            continue
        inst = cls()
        if inst.available():
            sources.append(inst)
    if not sources:
        raise RuntimeError("Brak skonfigurowanych zrodel discovery.")

    from collections import deque

    estimated_cost = 0.0
    new_leads_count = 0
    cities_processed = 0
    cities_skipped_no_results = 0
    drafts_made = 0
    # Bounded deque - zapobiega memory leak (1000+ items inside autonomous run)
    # plus tani slice. Plus oszczedza miejsce w JSON job.result.
    recent: deque = deque(maxlen=15)

    current_segment_label: str = segments_list[0]

    def _save_progress(current_city: str | None = None, status: str = "running"):
        """Update job.result + job.progress dla live UI updates.
        Wywolywane po kazdym mieście + zmianie statu w trakcie."""
        job.progress = new_leads_count
        job.total = target
        job.result = {
            "status": status,
            "current_city": current_city,
            "current_segment": current_segment_label,
            "segments": segments_list,
            "cities_processed": cities_processed,
            "cities_total": len(work_queue),  # multi-segment: total = segments x cities
            "new_leads_count": new_leads_count,
            "target_new_leads": target,
            "drafts_made": drafts_made,
            "estimated_cost_usd": round(estimated_cost, 3),
            "max_cost_usd": max_cost,
            "cities_skipped_no_results": cities_skipped_no_results,
            "recent": list(recent),  # deque maxlen=15, juz bounded
        }
        session.commit()

    _save_progress(status="starting")
    log.info(
        f"Job #{job.id} autonomous: target={target} budget=${max_cost} "
        f"segments={segments_list!r} cities={len(cities_list)} work_queue={len(work_queue)}"
    )

    for current_segment_label, city in work_queue:
        if _shutdown or _is_cancelled(session, job.id):
            log.info(f"Job #{job.id} stopped externally at city #{cities_processed}")
            break
        if new_leads_count >= target:
            log.info(f"Job #{job.id} TARGET REACHED ({new_leads_count}/{target})")
            break
        if estimated_cost >= max_cost:
            log.info(f"Job #{job.id} BUDGET REACHED (${estimated_cost:.2f}/${max_cost})")
            break

        city_name = city["name"]
        cities_processed += 1
        # Query budowane per (segment, miasto)
        query = f"{current_segment_label.replace('_', ' ')} {city_name}"

        # Live update - user widzi "Sprawdzam: Warszawa (sklep_papierniczy)"
        _save_progress(current_city=city_name)

        # Run search dla tego miasta
        try:
            places, _diag = run_search(
                sources,
                query=query,
                max_results_per_source=60,
                workspace_id=job.workspace_id,
                city_filter=city_name,
            )
            estimated_cost += len(sources) * 0.03
        except Exception as exc:
            log.warning(f"Job #{job.id} {current_segment_label}+{city_name!r} search failed: {exc}")
            recent.append({
                "name": city_name, "segment": current_segment_label,
                "status": "city_search_failed",
                "error": str(exc)[:120],
            })
            _save_progress(current_city=city_name)
            continue

        # Relevance filter - tylko nowe places (rename pl zeby nie shadow'owac p=payload)
        new_places_for_llm = [
            pl for pl in places if pl.website and pl.existing_lead_id is None
        ]
        existing_count = len(places) - len(new_places_for_llm)

        targets = []
        if new_places_for_llm:
            try:
                items, _ = score_relevance_batch(
                    new_places_for_llm, segment=current_segment_label,
                    city=city_name,
                    custom_description=custom_desc,
                )
                estimated_cost += 0.005  # LLM call
                for it in items:
                    if it.score >= threshold and 0 <= it.idx < len(new_places_for_llm):
                        targets.append(new_places_for_llm[it.idx])
            except Exception as exc:
                log.warning(f"Job #{job.id} relevance batch failed for {city_name}: {exc}")
                recent.append({
                    "name": city_name, "segment": current_segment_label,
                    "status": "city_relevance_failed",
                    "error": str(exc)[:120],
                })
                _save_progress(current_city=city_name)
                continue

        # Log per-city stats - user widzi co miasto dalo
        recent.append({
            "name": city_name,
            "segment": current_segment_label,
            "status": "city_scanned",
            "places_found": len(places),
            "duplicates_in_db": existing_count,
            "matching_relevance": len(targets),
        })
        _save_progress(current_city=city_name)

        if not targets:
            cities_skipped_no_results += 1
            continue

        # Research kazdego target lead - tylko ile potrzeba do celu
        remaining = target - new_leads_count
        targets = targets[: min(remaining, len(targets))]
        for place in targets:
            if _shutdown or _is_cancelled(session, job.id):
                break
            if estimated_cost >= max_cost:
                break
            try:
                lead_id, _result, was_researched = research_and_save(
                    place.website,
                    segment_hint=current_segment_label,
                    city_hint=city_name,
                    workspace_id=job.workspace_id,
                )
                if was_researched:
                    estimated_cost += 0.02  # LLM research call
                    new_leads_count += 1

                    drafted_now = False
                    # Auto-draft jak wystarczajaco wysoki score
                    if auto_draft_th is not None and _result is not None:
                        if _result.score.total >= auto_draft_th:
                            try:
                                from agent.generate import generate_draft_for_lead
                                generate_draft_for_lead(
                                    lead_id, workspace_id=job.workspace_id,
                                )
                                drafts_made += 1
                                drafted_now = True
                                estimated_cost += 0.04  # LLM draft generation
                            except Exception as exc:
                                log.warning(f"draft for #{lead_id} failed: {exc}")

                    # Per-lead live ticker entry
                    recent.append({
                        "name": (_result.company_name if _result else place.name),
                        "url": place.website,
                        "status": "researched",
                        "score": round(_result.score.total, 1) if _result else None,
                        "lead_id": lead_id,
                        "drafted": drafted_now,
                        "city": city_name,
                    })
                    _save_progress(current_city=city_name)
            except Exception as exc:
                log.warning(f"research for {place.website} failed: {exc}")
                recent.append({
                    "name": place.name, "url": place.website,
                    "status": "research_failed", "error": str(exc)[:120],
                    "city": city_name,
                })
                _save_progress(current_city=city_name)

    # Final save z reason
    stopped_reason = (
        "target_reached" if new_leads_count >= target
        else "budget_reached" if estimated_cost >= max_cost
        else "cancelled" if _is_cancelled(session, job.id) or _shutdown
        else "all_cities_processed"
    )
    return {
        "target_new_leads": target,
        "new_leads_count": new_leads_count,
        "drafts_made": drafts_made,
        "cities_processed": cities_processed,
        "cities_skipped_no_results": cities_skipped_no_results,
        "estimated_cost_usd": round(estimated_cost, 3),
        "max_cost_usd": max_cost,
        "stopped_reason": stopped_reason,
        "recent": list(recent),
    }


JOB_HANDLERS = {
    JobType.DISCOVERY_PIPELINE.value: handle_discovery_pipeline,
    JobType.RESEARCH_LEAD.value: handle_research_lead,
    JobType.BULK_RESEARCH_LEADS.value: handle_bulk_research_leads,
    JobType.ENRICH_LEAD.value: handle_enrich_lead,
    JobType.BULK_ENRICH_LEADS.value: handle_bulk_enrich_leads,
    JobType.GENERATE_DRAFT.value: handle_generate_draft,
    JobType.BULK_GENERATE_DRAFTS.value: handle_bulk_generate_drafts,
    JobType.SEND_DRAFT.value: handle_send_draft,
    JobType.POLL_WOODPECKER.value: handle_poll_woodpecker,
    JobType.AUTONOMOUS_DISCOVERY.value: handle_autonomous_discovery,
}


# ─── Worker loop ────────────────────────────────────────────────────────

def _recover_zombie_jobs() -> None:
    """Startup recovery: marker RUNNING jobow z poprzedniego procesu jako FAILED.

    Worker pickuje tylko PENDING - jak crashne / Railway zredeploya w trakcie
    joba, status RUNNING zostaje w DB i nikt go nie podejmie. Frontend pokazuje
    "Praca w tle 1" mimo ze nic nie chodzi. Przy starcie czyscimy te zombie.

    Wrapped w try/except - failure tutaj NIE moze zabic workera (lepiej dzialac
    z paroma zombie niz w ogole nie startowac).
    """
    try:
        with SessionLocal() as session:
            try:
                stale = session.execute(
                    select(Job).where(Job.status == JobStatus.RUNNING.value)
                ).scalars().all()
                if not stale:
                    log.info("Zombie recovery: no orphaned RUNNING jobs found")
                    return
                for j in stale:
                    j.status = JobStatus.FAILED.value
                    j.last_error = "Worker restarted before job completed - re-trigger manually"
                    j.completed_at = datetime.now(timezone.utc)
                    log.warning(f"Zombie job #{j.id} ({j.type}) -> FAILED (worker restart)")
                session.commit()
                log.info(f"Zombie recovery: cleaned {len(stale)} orphaned jobs")
            except Exception:
                session.rollback()
                raise
    except Exception as exc:
        log.exception(f"Zombie recovery failed (non-fatal, continuing): {exc}")


def _is_cancelled(session: Session, job_id: int) -> bool:
    """Sprawdza w DB czy user anulowal joba. Defensywne - bierze tylko
    status osobnym SELECT zamiast refreshowac ORM obiekt (eliminuje
    DetachedInstanceError gdy handler robi commitsy w petli).
    """
    try:
        status = session.execute(
            select(Job.status).where(Job.id == job_id)
        ).scalar_one_or_none()
        return status == JobStatus.CANCELLED.value
    except Exception as exc:
        log.warning(f"_is_cancelled check failed for job #{job_id}: {exc}")
        return False


def claim_next_job(session: Session) -> Job | None:
    """Wybiera najstarsze pending job i flaguje running. Atomically.

    Postgres: uzywamy SELECT ... FOR UPDATE SKIP LOCKED - dwa watki nie
    zclaimuja tego samego joba (kazdy widzi tylko unlocked rows).
    SQLite: brak SKIP LOCKED, polegamy na sekwencyjnym ldostepie sesji.
    """
    from sqlalchemy import select as _sel
    q = (
        _sel(Job)
        .where(Job.status == JobStatus.PENDING.value)
        .order_by(Job.created_at)
        .limit(1)
    )
    # Detect dialect - SQLite nie wspiera SKIP LOCKED
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        q = q.with_for_update(skip_locked=True)
    job = session.execute(q).scalar_one_or_none()
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
            # Patrol bookkeeping: jak job byl odpalony przez patrol (payload
            # ma _patrol_id), inkrementuj stats. Idempotentne - blad nie blokuje
            # zakonczenia joba.
            patrol_id = (job.payload or {}).get("_patrol_id") if job.payload else None
            if patrol_id and isinstance(result, dict):
                try:
                    leads_found = int(result.get("researched", 0))
                    if leads_found > 0:
                        session.execute(
                            sa_update(PatrolSchedule)
                            .where(PatrolSchedule.id == patrol_id)
                            .values(total_leads_found=PatrolSchedule.total_leads_found + leads_found)
                        )
                except Exception as exc:
                    log.warning(f"Patrol #{patrol_id} stats update failed: {exc}")
            # Cancel check - re-fetch zamiast session.refresh (defensive: handler
            # mogl rollbackowac sesje, mogla byc rozłączona po długim runtime).
            current_status = session.execute(
                select(Job.status).where(Job.id == job_id)
            ).scalar_one_or_none()
            if current_status == JobStatus.CANCELLED.value:
                job.result = result
                job.completed_at = datetime.now(timezone.utc)
                _log_event(session, job.workspace_id, "INFO", "job_cancelled",
                           f"Job #{job.id} ({job.type}) cancelled by user (partial result saved)")
                session.commit()
                log.info(f"Job #{job.id} CANCELLED mid-run - partial {result}")
                return
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


def _patrol_tick() -> int:
    """Sprawdza wszystkie aktywne PatrolSchedule i triggeruje DISCOVERY_PIPELINE
    job dla tych ktorych nadszedl next_run_at.

    Zwraca liczbe utworzonych jobow. Wrap-uje wszystko w try/except - failure
    tutaj NIE moze przerwac worker loop'a (lepiej dzialac bez patroli niz
    wcale).
    """
    from web.jobs_dispatcher import create_job, find_active_job
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    triggered = 0
    try:
        with SessionLocal() as session:
            due = session.execute(
                select(PatrolSchedule).where(
                    PatrolSchedule.enabled == True,  # noqa: E712
                    PatrolSchedule.next_run_at <= now,
                )
            ).scalars().all()

            for patrol in due:
                # Daily cap reset (UTC midnight)
                today_anchor = now.replace(hour=0, minute=0, second=0, microsecond=0)
                if patrol.day_anchor is None or patrol.day_anchor < today_anchor:
                    patrol.runs_today = 0
                    patrol.day_anchor = today_anchor

                # Cap dzienny: jak juz zrobiono cap_per_day uruchomien, czekaj do jutra
                if patrol.runs_today >= patrol.cap_per_day:
                    patrol.next_run_at = today_anchor + timedelta(days=1)
                    log.info(
                        f"Patrol #{patrol.id} ({patrol.name}): daily cap reached "
                        f"({patrol.runs_today}/{patrol.cap_per_day}), sleeping until tomorrow"
                    )
                    continue

                # Skip jak juz chodzi job tego workspace'u (nie duplikujemy)
                active = find_active_job(
                    session, patrol.workspace_id,
                    job_types=[JobType.DISCOVERY_PIPELINE.value, JobType.BULK_RESEARCH_LEADS.value],
                )
                if active is not None:
                    # Przesun next_run_at o pol godziny - sproboj pozniej
                    patrol.next_run_at = now + timedelta(minutes=30)
                    log.info(
                        f"Patrol #{patrol.id}: workspace ma juz aktywny job #{active.id}, "
                        f"reschedule na +30min"
                    )
                    continue

                # Buduj query (z pierwszego segment + pierwszej location, plus custom)
                segments = patrol.segments or ["inne"]
                locations = patrol.locations or [""]
                segment = segments[(patrol.total_runs or 0) % len(segments)]
                location = locations[(patrol.total_runs or 0) % len(locations)]
                phrase = patrol.custom_target or segment.replace("_", " ")
                query = f"{phrase} {location}".strip()

                payload = {
                    "query": query,
                    "sources": patrol.sources or ["google_places"],
                    "max_per_source": patrol.max_per_run,
                    "segment": segment,
                    "location": location or None,
                    "custom_description": patrol.custom_target,
                    "use_relevance_filter": True,
                    "relevance_threshold": patrol.relevance_threshold,
                    "auto_research": True,
                    "auto_draft_threshold": patrol.auto_draft_threshold,
                    "apply_city_filter": bool(location),
                    "_patrol_id": patrol.id,
                }
                create_job(
                    session, job_type=JobType.DISCOVERY_PIPELINE,
                    workspace_id=patrol.workspace_id, user_id=patrol.user_id,
                    payload=payload,
                )
                patrol.last_run_at = now
                patrol.next_run_at = now + timedelta(hours=patrol.frequency_hours)
                patrol.runs_today = (patrol.runs_today or 0) + 1
                patrol.total_runs = (patrol.total_runs or 0) + 1
                triggered += 1
                log.info(
                    f"Patrol #{patrol.id} ({patrol.name}) TRIGGERED: query={query!r} "
                    f"next={patrol.next_run_at} runs_today={patrol.runs_today}/{patrol.cap_per_day}"
                )
            session.commit()
    except Exception as exc:
        log.exception(f"Patrol tick failed (non-fatal): {exc}")
    return triggered


def _purge_trash_tick() -> int:
    """Auto-purge kosza: hard-delete leady z deleted_at starszym niz
    RECYCLE_BIN_DAYS dni (default 7). Cascade na drafty (relationship cascade).

    Wrap w try/except - failure nie blokuje worker loop. Audit log per workspace
    z liczba usunietych - user widzi w timeline ze kosz sie sam wyczyscil.
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECYCLE_BIN_DAYS)
    deleted_count = 0
    try:
        with SessionLocal() as session:
            stale = session.execute(
                select(Lead).where(
                    Lead.deleted_at.is_not(None),
                    Lead.deleted_at < cutoff,
                )
            ).scalars().all()
            if not stale:
                return 0
            # Grupuj po workspace_id do audit log
            by_ws: dict[int | None, list[int]] = {}
            for lead in stale:
                by_ws.setdefault(lead.workspace_id, []).append(lead.id)
                session.delete(lead)  # cascade -> drafty
                deleted_count += 1
            # Audit per workspace
            for ws_id, ids in by_ws.items():
                if ws_id is None:
                    continue
                session.add(Event(
                    workspace_id=ws_id,
                    type="trash.auto_purged",
                    level="INFO",
                    source="worker",
                    message=f"Auto-purge kosza: {len(ids)} leadow usunietych po {RECYCLE_BIN_DAYS} dniach",
                    payload={
                        "deleted_count": len(ids),
                        "lead_ids": ids[:50],  # cap zeby nie napuchla baza
                        "recycle_bin_days": RECYCLE_BIN_DAYS,
                    },
                ))
            session.commit()
            log.info(
                f"Trash auto-purge: removed {deleted_count} leads "
                f"(deleted_at older than {RECYCLE_BIN_DAYS} days)"
            )
    except Exception as exc:
        log.exception(f"Trash auto-purge failed (non-fatal): {exc}")
    return deleted_count


def _heartbeat() -> None:
    """Zapisz "pulse" do tabeli Event - pozwala backendowi sprawdzic czy worker zyje.

    workspace_id=NULL (system-level event, nie nalezy do zadnego workspace -
    FK jest nullable w schemie). Backend filtruje Event.type='worker.heartbeat'
    przy /api/_health/worker - jak ostatni heartbeat > 2 min temu, worker padl.
    """
    try:
        with SessionLocal() as session:
            session.add(Event(
                workspace_id=None,
                type="worker.heartbeat",
                level="INFO",
                source="worker",
                message="alive",
                payload={"poll_interval": POLL_INTERVAL_S, "max_retries": MAX_RETRIES},
            ))
            session.commit()
    except Exception as exc:
        log.warning(f"Heartbeat failed (non-fatal): {exc}")


def _job_worker_loop(worker_idx: int) -> None:
    """Pojedynczy watek pool'a - claimuje + wykonuje joby w petli.
    Konczy gdy _shutdown jest True.
    """
    log_w = logging.getLogger(f"worker[{worker_idx}]")
    while not _shutdown:
        try:
            job_meta: tuple[int, str, int] | None = None
            with SessionLocal() as session:
                job = claim_next_job(session)
                if job is not None:
                    job_meta = (job.id, job.type, job.workspace_id)
            if job_meta is None:
                time.sleep(POLL_INTERVAL_S)
                continue
            job_id, job_type, job_ws = job_meta
            log_w.info(f"Job #{job_id} CLAIMED type={job_type} ws={job_ws}")
            execute_job(job_id)
        except Exception as exc:
            log_w.exception(f"Worker loop error: {exc}")
            time.sleep(POLL_INTERVAL_S)


def loop_forever() -> None:
    """Worker entry point - thread pool (paralleizm) + tick scheduler.

    Pool N watkow przetwarza joby rownolegle (claim_next_job z SKIP LOCKED).
    Glowny watek (ten) tylko schedule'uje ticki (patrol, heartbeat, purge).
    """
    from concurrent.futures import ThreadPoolExecutor

    n_workers = int(os.getenv("WORKER_THREADS") or 3)
    log.info(
        f"Worker starting (pool={n_workers}, poll {POLL_INTERVAL_S}s, "
        f"max retries {MAX_RETRIES}, patrol tick {PATROL_TICK_S}s, "
        f"trash purge {PURGE_TICK_S}s after {RECYCLE_BIN_DAYS} days)"
    )
    init_db()
    _recover_zombie_jobs()
    _heartbeat()
    _purge_trash_tick()
    last_patrol_tick = 0.0
    last_heartbeat = time.time()
    last_purge_tick = time.time()

    # Pool watkow do przetwarzania jobow rownolegle
    executor = ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="job-worker")
    futures = [executor.submit(_job_worker_loop, i) for i in range(n_workers)]

    # Glowny watek - scheduler (tick patrol/heartbeat/purge)
    try:
        while not _shutdown:
            try:
                now_ts = time.time()
                if now_ts - last_patrol_tick >= PATROL_TICK_S:
                    last_patrol_tick = now_ts
                    _patrol_tick()
                if now_ts - last_heartbeat >= HEARTBEAT_S:
                    last_heartbeat = now_ts
                    _heartbeat()
                if now_ts - last_purge_tick >= PURGE_TICK_S:
                    last_purge_tick = now_ts
                    _purge_trash_tick()
                time.sleep(POLL_INTERVAL_S)
            except Exception as exc:
                log.exception(f"Scheduler loop error: {exc}")
                time.sleep(POLL_INTERVAL_S)
    finally:
        log.info("Worker shutdown - waiting for thread pool")
        executor.shutdown(wait=True, cancel_futures=False)
        # Drain futures dla logow
        for f in futures:
            if f.exception():
                log.error(f"Worker thread exited with error: {f.exception()}")
    log.info("Worker shutdown clean")


if __name__ == "__main__":
    loop_forever()
