"""Generate cold email drafts from researched leads.

Reads:
    - leads.research_data (ResearchResult JSON, includes concrete_hooks)
    - prompts/brand.py (Artmaker positioning — single source of truth)
    - prompts/few_shot_examples/*.md (owner's real writing — voice anchor; optional)

Writes:
    - email_drafts row with status=draft (subject + snippet1..snippet5 Woodpecker-compatible)
    - leads.status -> drafted

Personalization rule: every snippet that references the lead must use a
concrete_hook from research_data. No generic "hope this finds you well"
openers. Subject must be specific to the lead's segment and what we offer.

CLI usage:
    python -m agent.generate --lead-id 42
    python -m agent.generate --all-researched   # bulk for all researched leads
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select

from core.config import PROJECT_ROOT, settings
from core.db import (
    DraftStatus,
    EmailDraft,
    Lead,
    LeadStatus,
    SessionLocal,
    init_db,
)
from core.kill_switch import is_stopped
from core.llm import estimate_cost_usd, parse_structured
from core.logger import logger, setup_logging
from prompts.brand import BRAND_CONTEXT


FEW_SHOT_DIR = PROJECT_ROOT / "prompts" / "few_shot_examples"


class EmailDraftPayload(BaseModel):
    """Structured output from the LLM. Maps directly onto the EmailDraft DB row.

    Woodpecker convention: subject + 1-5 snippets, where snippets are the
    body paragraphs assembled in order. Keep each snippet 1-3 sentences max.
    """

    subject: str = Field(
        description="Konkretny, krótki temat maila (max 60 znaków). Bez ogólników."
    )
    snippet1: str = Field(
        description="Otwarcie. MUSI nawiązać do konkretu z research_data.concrete_hooks."
    )
    snippet2: str = Field(
        description="Most do oferty Artmakera — co konkretnie możemy im dać."
    )
    snippet3: str = Field(
        description="Konkretna propozycja wartości (cena producenta / private label / specyfikacja)."
    )
    snippet4: Optional[str] = Field(
        default=None,
        description="Opcjonalny social proof / liczba (jeśli pasuje, inaczej null).",
    )
    snippet5: str = Field(
        description="CTA — propozycja krótkiej rozmowy lub przesłania katalogu/wyceny."
    )


def _load_few_shot_examples() -> str:
    """Concatenate any *.md files in prompts/few_shot_examples/ as voice anchor.

    Returns empty string if dir is empty or missing — generation still works,
    just without owner-specific voice signal.
    """
    if not FEW_SHOT_DIR.exists():
        return ""
    chunks = []
    for path in sorted(FEW_SHOT_DIR.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        try:
            chunks.append(
                f"### Przykład: {path.stem}\n{path.read_text(encoding='utf-8').strip()}"
            )
        except Exception:
            continue
    return "\n\n".join(chunks)


def _build_user_prompt(lead: Lead) -> str:
    """Pack the lead's research data into a compact prompt the LLM grounds on."""
    rd = lead.research_data or {}
    hooks = rd.get("concrete_hooks") or []
    hook_lines = "\n".join(
        f"- {h.get('text', '').strip()}" for h in hooks if h.get("text")
    ) or "(brak haków — bądź ostrożny, oprzyj się o segment i nazwę firmy)"

    rationale = rd.get("rationale") or "(brak)"
    monthly = rd.get("estimated_monthly_volume") or "(nieznane)"
    contact = lead.contact_name or "(brak nazwiska decydenta)"
    segment = rd.get("segment") or lead.segment or "inne"

    return (
        f"## Lead\n"
        f"Firma: {lead.company_name}\n"
        f"Strona: {lead.website or '(brak)'}\n"
        f"Miasto: {lead.city or '(brak)'}\n"
        f"Segment: {segment}\n"
        f"Kontakt: {contact}\n"
        f"Email do wysyłki: {lead.email or '(brak — używaj formy bezosobowej lub Pan/Pani)'}\n"
        f"Szacunkowy wolumen: {monthly}\n\n"
        f"## Konkretne haki z researchu (UŻYJ ich w mailu, nie zmyślaj nowych)\n"
        f"{hook_lines}\n\n"
        f"## Uzasadnienie scoringu\n"
        f"{rationale}\n\n"
        f"## Twoje zadanie\n"
        f"Wygeneruj cold email B2B od Artmakera do tej firmy. ZASADY:\n"
        f"1. snippet1 MUSI nawiązać do konkretnego haka z listy powyżej (cytuj/parafrazuj).\n"
        f"2. Brzmienie polskie, naturalne, bez korpomowy, bez 'mam nadzieję, że ta wiadomość zastanie...'.\n"
        f"3. Subject < 60 znaków, konkretny (np. 'Hurtowe ceny farb dla {lead.company_name}'), bez clickbaitów.\n"
        f"4. Wartość: cena producenta z naszych chińskich fabryk + opcja private label.\n"
        f"5. CTA: krótka rozmowa 15 min albo przesłanie katalogu/cennika — coś niskiego ryzyka.\n"
        f"6. Mail całość: 80-150 słów. Krótko."
    )


def _build_system_prompt() -> str:
    """System prompt: brand context + voice anchor (few-shots) if present."""
    examples = _load_few_shot_examples()
    examples_block = (
        f"\n\n## Przykłady stylu autora (trzymaj się tego brzmienia)\n{examples}"
        if examples
        else ""
    )
    return (
        f"{BRAND_CONTEXT}\n\n"
        "Jesteś copywriterem B2B Artmakera. Piszesz krótkie, personalizowane "
        "cold maile do polskich firm. Twój styl: konkret, brak korpomowy, "
        "naturalny ton. Każdy mail MUSI zawierać konkret o adresacie zaczerpnięty "
        "z dostarczonych haków researchu — nie wolno generować generycznych "
        "otwarć ani zmyślać faktów. Zwracasz wyłącznie JSON zgodny ze schematem."
        f"{examples_block}"
    )


def generate_draft_for_lead(
    lead_id: int,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> int:
    """Generate and persist a cold email draft for one lead. Returns draft id.

    Skips and returns the existing id if the lead already has a non-rejected
    draft (one active draft per lead until owner approves/rejects). To
    regenerate, reject the old draft first.
    """
    provider = (provider or settings.llm_provider).lower()
    if provider == "anthropic":
        model = model or settings.anthropic_model
    elif provider == "gemini":
        model = model or settings.gemini_model

    with SessionLocal() as session:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f"Lead #{lead_id} nie istnieje.")
        existing = session.execute(
            select(EmailDraft.id).where(
                EmailDraft.lead_id == lead_id,
                EmailDraft.status != DraftStatus.REJECTED.value,
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.bind(source="generate").info(
                f"Lead #{lead_id} already has draft #{existing}; skipping."
            )
            return existing
        system = _build_system_prompt()
        user = _build_user_prompt(lead)

    payload, usage = parse_structured(
        provider=provider,
        model=model,
        system=system,
        user=user,
        output_schema=EmailDraftPayload,
        max_tokens=2000,
    )

    full_preview = _assemble_preview(payload)
    cost = estimate_cost_usd(provider, model, usage)
    logger.bind(source="generate").info(
        f"Draft generated for lead #{lead_id} via {provider}/{model}; "
        f"~${cost} usd; subject={payload.subject!r}"
    )

    with SessionLocal() as session:
        draft = EmailDraft(
            lead_id=lead_id,
            template_variant="cold_v1",
            subject=payload.subject,
            snippet1=payload.snippet1,
            snippet2=payload.snippet2,
            snippet3=payload.snippet3,
            snippet4=payload.snippet4,
            snippet5=payload.snippet5,
            full_preview=full_preview,
            status=DraftStatus.DRAFT.value,
            generated_by_model=f"{provider}/{model}",
        )
        session.add(draft)
        lead = session.get(Lead, lead_id)
        if lead is not None:
            lead.status = LeadStatus.DRAFTED.value
        session.commit()
        return draft.id


def _assemble_preview(payload: EmailDraftPayload) -> str:
    """Stitch snippets into a human-readable preview body."""
    parts = [
        f"Subject: {payload.subject}",
        "",
        payload.snippet1,
        "",
        payload.snippet2,
        "",
        payload.snippet3,
    ]
    if payload.snippet4:
        parts.extend(["", payload.snippet4])
    parts.extend(["", payload.snippet5])
    return "\n".join(parts)


def generate_all_researched(
    *,
    provider: str | None = None,
    model: str | None = None,
    min_score: float = 0.0,
) -> tuple[int, int]:
    """Bulk-generate drafts for every researched lead without an active draft.

    Returns (made, failed). Skips leads with score < min_score.
    """
    with SessionLocal() as session:
        candidate_ids = session.execute(
            select(Lead.id).where(
                Lead.status == LeadStatus.RESEARCHED.value,
                Lead.score >= min_score,
            )
        ).scalars().all()

    made, failed = 0, 0
    for lead_id in candidate_ids:
        if is_stopped():
            logger.bind(source="generate").warning("STOP.txt detected — halting bulk generate.")
            break
        try:
            generate_draft_for_lead(lead_id, provider=provider, model=model)
            made += 1
        except Exception as exc:
            failed += 1
            logger.bind(source="generate").exception(
                f"Draft for lead #{lead_id} failed: {exc}"
            )
    return made, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate email draft(s) for researched lead(s).")
    parser.add_argument("--lead-id", type=int, default=None, help="Single lead id")
    parser.add_argument("--all-researched", action="store_true", help="All leads with status=researched")
    parser.add_argument("--min-score", type=float, default=0.0, help="Skip leads below this score (only with --all-researched)")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    setup_logging()
    init_db()

    if is_stopped():
        logger.bind(source="generate").warning("STOP.txt present — generate aborted.")
        return

    if args.lead_id is not None:
        draft_id = generate_draft_for_lead(args.lead_id, provider=args.provider, model=args.model)
        print(f"Draft #{draft_id} created for lead #{args.lead_id}.")
        return
    if args.all_researched:
        made, failed = generate_all_researched(
            provider=args.provider, model=args.model, min_score=args.min_score
        )
        print(f"Bulk generate: {made} drafts created, {failed} failures.")
        return
    parser.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
