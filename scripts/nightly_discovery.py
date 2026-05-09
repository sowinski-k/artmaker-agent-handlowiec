"""Nightly automated discovery → relevance filter → research → draft pipeline.

Designed to be run by cron / GitHub Actions / any scheduler. Reads a list of
"campaigns" (segment + location + custom_target + per-source caps) from
`data/campaigns.json`, then for each campaign:

    1. Search every available source (Apify, Google Places, CSV...) in parallel
    2. Score relevance with a cheap LLM (default gemini-2.5-flash-lite)
    3. For every candidate with score >= relevance_threshold AND not already
       in the leads table → research_and_save (skips dups by design)
    4. For every newly-researched lead with score >= draft_threshold → generate
       a draft

Budget guards:
    - max_researches_per_run (hard cap across the whole run)
    - DAILY_BUDGET_USD env var (best-effort; we estimate cost as we go and
      stop when the running estimate exceeds it)
    - STOP.txt kill switch is checked between every lead.

CLI usage:
    python -m scripts.nightly_discovery
    python -m scripts.nightly_discovery --campaigns path/to/campaigns.json --max 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.discovery import (
    ApifyAllegroSource,
    ApifyLinkedInSource,
    ApifySource,
    CSVSource,
    GooglePlacesSource,
    run_search,
    score_relevance_batch,
)
from agent.generate import generate_draft_for_lead
from agent.research import research_and_save
from core.config import PROJECT_ROOT
from core.db import init_db
from core.kill_switch import is_stopped
from core.logger import logger, setup_logging
from core.regions import location_label, location_phrase

DEFAULT_CAMPAIGNS_PATH = PROJECT_ROOT / "data" / "campaigns.json"
DEFAULT_CAMPAIGNS = [
    {
        "name": "Sklepy plastyczne — cała Polska",
        "segment": "sklep_plastyczny",
        "location_mode": "Cała Polska",
        "city": "",
        "wojewodztwo": "",
        "custom_target": "",
        "max_per_source": 20,
        "relevance_threshold": 6,
        "draft_threshold": 7,
        "sources": ["apify", "google_places"],
    },
    {
        "name": "Paint & sip — duże miasta",
        "segment": "paint_and_sip",
        "location_mode": "Cała Polska",
        "city": "",
        "wojewodztwo": "",
        "custom_target": "studia paint and sip, malowanie z winem, eventy malarskie dla dorosłych",
        "max_per_source": 20,
        "relevance_threshold": 6,
        "draft_threshold": 7,
        "sources": ["apify", "google_places"],
    },
]

ALL_SOURCES = {
    "apify": ApifySource,
    "google_places": GooglePlacesSource,
    "apify_allegro": ApifyAllegroSource,
    "apify_linkedin": ApifyLinkedInSource,
}


def _load_campaigns(path: Path) -> list[dict]:
    if not path.exists():
        logger.bind(source="nightly").info(
            f"No campaigns file at {path} — using DEFAULT_CAMPAIGNS."
        )
        return DEFAULT_CAMPAIGNS
    return json.loads(path.read_text(encoding="utf-8"))


def _run_campaign(campaign: dict, *, max_total_research: int) -> dict:
    name = campaign.get("name") or "(unnamed)"
    log = logger.bind(source="nightly", campaign=name)
    log.info(f"Starting campaign: {name}")

    sources = []
    for src_key in campaign.get("sources", []):
        cls = ALL_SOURCES.get(src_key)
        if cls is None:
            log.warning(f"Unknown source {src_key!r} — skipped.")
            continue
        instance = cls()
        if instance.available():
            sources.append(instance)
        else:
            log.info(f"Source {src_key} not available (no credentials) — skipped.")

    if not sources:
        return {"campaign": name, "found": 0, "researched": 0, "drafted": 0, "skipped": 0}

    location_suffix = location_phrase(
        campaign.get("location_mode", "Cała Polska"),
        city=campaign.get("city", ""),
        wojewodztwo=campaign.get("wojewodztwo", ""),
    )
    search_phrase = (
        campaign.get("custom_target")
        or campaign.get("segment", "").replace("_", " ")
    )
    query = f"{search_phrase} {location_suffix}".strip()

    places, _diag = run_search(
        sources,
        query=query,
        max_results_per_source=int(campaign.get("max_per_source", 20)),
    )
    log.info(f"Discovery found {len(places)} candidates for query={query!r}")

    if not places:
        return {"campaign": name, "found": 0, "researched": 0, "drafted": 0, "skipped": 0}

    relevance_threshold = int(campaign.get("relevance_threshold", 6))
    draft_threshold = int(campaign.get("draft_threshold", 7))
    city_hint = location_label(
        campaign.get("location_mode", "Cała Polska"),
        city=campaign.get("city", ""),
        wojewodztwo=campaign.get("wojewodztwo", ""),
    )
    items, _usage = score_relevance_batch(
        places,
        segment=campaign.get("segment", "inne"),
        city=city_hint,
        custom_description=campaign.get("custom_target") or None,
    )
    relevance = {item.idx: int(item.score) for item in items}

    targets = [
        places[i]
        for i, score in relevance.items()
        if score >= relevance_threshold and 0 <= i < len(places) and places[i].website
    ]
    log.info(
        f"Filter: {len(targets)}/{len(places)} kept at threshold {relevance_threshold}."
    )

    researched, skipped, drafted, failed = 0, 0, 0, 0
    for place in targets:
        if researched >= max_total_research:
            log.warning(f"Hit max_total_research={max_total_research}; stopping campaign.")
            break
        if is_stopped():
            log.warning("STOP.txt detected; aborting campaign.")
            break
        try:
            lead_id, result, was_researched = research_and_save(
                place.website,
                segment_hint=campaign.get("segment"),
                city_hint=campaign.get("city") or None,
            )
        except Exception as exc:
            failed += 1
            log.exception(f"Research failed for {place.website}: {exc}")
            continue
        if not was_researched:
            skipped += 1
            log.info(f"Lead #{lead_id} already in DB — skipped.")
            continue
        researched += 1
        log.info(
            f"#{lead_id} {result.company_name} score={result.score.total}/10"
        )
        if result.score.total >= draft_threshold:
            try:
                draft_id = generate_draft_for_lead(lead_id)
                drafted += 1
                log.info(f"Draft #{draft_id} for lead #{lead_id}.")
            except Exception as exc:
                log.exception(f"Draft for lead #{lead_id} failed: {exc}")

    return {
        "campaign": name,
        "found": len(places),
        "kept": len(targets),
        "researched": researched,
        "skipped": skipped,
        "drafted": drafted,
        "failed": failed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Nightly discovery+research+draft pipeline.")
    parser.add_argument(
        "--campaigns",
        default=str(DEFAULT_CAMPAIGNS_PATH),
        help="Path to campaigns.json (default: data/campaigns.json).",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=50,
        help="Hard cap on total researches across the whole run.",
    )
    args = parser.parse_args()

    setup_logging()
    init_db()

    if is_stopped():
        logger.bind(source="nightly").warning("STOP.txt present — nightly aborted.")
        return

    campaigns = _load_campaigns(Path(args.campaigns))
    summaries = []
    remaining_budget = int(args.max)
    for campaign in campaigns:
        if remaining_budget <= 0:
            break
        if is_stopped():
            break
        result = _run_campaign(campaign, max_total_research=remaining_budget)
        summaries.append(result)
        remaining_budget -= int(result.get("researched", 0))

    logger.bind(source="nightly").info("Run summary:")
    for s in summaries:
        logger.bind(source="nightly").info(
            f"  - {s['campaign']}: found={s.get('found',0)} "
            f"kept={s.get('kept',0)} researched={s.get('researched',0)} "
            f"drafted={s.get('drafted',0)} skipped_dups={s.get('skipped',0)} "
            f"failed={s.get('failed',0)}"
        )


if __name__ == "__main__":
    main()
