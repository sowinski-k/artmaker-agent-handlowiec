"""Generate cold email drafts from researched leads.

Reads:
    - leads.research_data (ResearchResult JSON, includes concrete_hooks)
    - prompts/brand.py (Artmaker positioning - single source of truth)
    - prompts/few_shot_examples/*.md (owner's real writing - voice anchor; optional)

Writes:
    - email_drafts row with status=draft (subject + snippet1..snippet5 Woodpecker-compatible)
    - leads.status -> drafted

Personalization rule: every snippet that references the lead must use a
concrete_hook from research_data. No generic "hope this finds you well"
openers. Subject must be specific to the lead's segment and what we offer.

Anti-AI defaults:
    - temperature=0.85 (escape deterministic AI cliche basin)
    - hard rules in the prompt (no em-dash, no buzzwords, short sentences)
    - _strip_ai_artifacts post-process strips dashes / smart quotes / leftover
      AI tells before the draft hits the DB

CLI usage:
    python -m agent.generate --lead-id 42
    python -m agent.generate --all-researched   # bulk for all researched leads
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Literal, Optional

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


# Drafting temperature - escape the deterministic AI cliche basin while
# staying coherent. 0.85 is the sweet spot for cold email copy.
DRAFT_TEMPERATURE = 0.85


# Punctuation substitutions: kill em-dash, en-dash, smart quotes that AI
# detectors love and that scream "generated".
_PUNCT_REPLACEMENTS = {
    "—": "-",   # em-dash
    "–": "-",   # en-dash
    "−": "-",   # minus sign
    "“": '"',   # left double smart quote
    "”": '"',   # right double smart quote
    "„": '"',   # double low-9 quote (Polish opening)
    "‚": "'",   # single low-9 quote
    "‘": "'",   # left single smart quote
    "’": "'",   # right single smart quote / apostrophe
    "«": '"',   # left guillemet
    "»": '"',   # right guillemet
    "…": "...", # ellipsis
    " ": " ",   # non-breaking space
}

# Phrases the LLM tends to slip in despite instructions. Hard-strip them.
# Order matters: longer first to avoid partial matches.
_AI_CLICHES = [
    r"Mam nadzieję, że ta wiadomość zastanie [^.,!?\n]*[.,!?]?\s*",
    r"Mam nadzieję, że [^.,!?\n]*?dobrym zdrowiu[.,!?]?\s*",
    r"Pozdrawiam serdecznie[,.!]?\s*",
    r"Z wyrazami szacunku[,.!]?\s*",
    r"Z poważaniem[,.!]?\s*",
    r"Pragnę (?:poinformować|zaproponować|przedstawić)[^.,!?\n]*[.,!?]?\s*",
    r"Chciał(?:a)?bym (?:zaproponować|przedstawić)[^.,!?\n]*[.,!?]?\s*",
    r"Korzystając z okazji[^.,!?\n]*[.,!?]?\s*",
    r"Uprzejmie informuję[^.,!?\n]*[.,!?]?\s*",
    r"W dzisiejszych czasach\s+",
]
_AI_CLICHE_PATTERN = re.compile("|".join(_AI_CLICHES), re.IGNORECASE)


def _strip_ai_artifacts(text: str | None) -> str | None:
    """Punctuation + cliche scrub. Idempotent.

    - Replaces em-dash / en-dash / smart quotes with ASCII equivalents.
    - Removes blacklisted AI/corpo phrases the model occasionally smuggles in.
    - Collapses runs of spaces and trims edges.

    Returns the cleaned string, or None if input was None/empty.
    """
    if not text:
        return text
    out = text
    for src, dst in _PUNCT_REPLACEMENTS.items():
        out = out.replace(src, dst)
    out = _AI_CLICHE_PATTERN.sub("", out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


class EmailDraftPayload(BaseModel):
    """Structured output from the LLM. Maps directly onto the EmailDraft DB row.

    Woodpecker convention: subject + 1-5 snippets, where snippets are the
    body paragraphs assembled in order. Keep each snippet 1-3 sentences max.
    """

    offer_track: Literal["b2b_panel", "private_label", "both"] = Field(
        description=(
            "Która oferta Artmakera jest dla tego leada: "
            "'b2b_panel' = panel B2B z magazynu PL + dostawa 24h (Track B, default), "
            "'private_label' = produkcja w Chinach pod marka własną (Track A), "
            "'both' = sugerujemy obie, B teraz + A jako rozwoj na pozniej."
        )
    )
    subject: str = Field(
        description="Konkretny, krótki temat maila (max 50 znaków). Bez ogólników, bez 'Oferta:'."
    )
    snippet1: str = Field(
        description="Otwarcie. MUSI nawiązać do konkretu z research_data.concrete_hooks."
    )
    snippet2: str = Field(
        description="Most do wybranej oferty - co konkretnie im dajemy w ramach offer_track."
    )
    snippet3: str = Field(
        description="Konkretna propozycja wartości - liczby, terminy, czym się różnimy."
    )
    snippet4: Optional[str] = Field(
        default=None,
        description="Opcjonalny social proof / liczba (jeśli pasuje, inaczej null)."
    )
    snippet5: str = Field(
        description="CTA jako pytanie - niskim wysiłkiem dla odbiorcy."
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
    ) or "(brak haków - oprzyj się TYLKO na nazwie i segmencie, nie zmyślaj)"

    rationale = rd.get("rationale") or "(brak)"
    monthly = rd.get("estimated_monthly_volume") or "(nieznane)"
    contact = lead.contact_name or "(nieznany)"
    segment = rd.get("segment") or lead.segment or "inne"

    # Tone hint: if we have a first name only, it's likely informal.
    if lead.contact_name and " " not in lead.contact_name.strip():
        tone_hint = (
            f"Kontakt podany imieniem ({contact}) - mail luźniejszy, "
            "po imieniu, ale bez przesady."
        )
    elif lead.contact_name:
        tone_hint = (
            f"Mamy nazwisko ({contact}) - forma Pan/Pani, ale naturalna, nie sztywna."
        )
    else:
        tone_hint = (
            "Brak konkretnej osoby - bezosobowo do firmy. "
            "Bez 'Szanowni Państwo', otwórz konkretem."
        )

    # Track recommendation hint based on segment - the LLM has final say.
    track_hint = _suggest_track_hint(segment, monthly)

    return (
        f"## Lead do napisania\n"
        f"Firma: {lead.company_name}\n"
        f"Strona: {lead.website or '(brak)'}\n"
        f"Miasto: {lead.city or '(brak)'}\n"
        f"Segment: {segment}\n"
        f"Kontakt: {contact}\n"
        f"Email do wysyłki: {lead.email or '(brak)'}\n"
        f"Szacunkowy wolumen B2B: {monthly}\n"
        f"Ton: {tone_hint}\n\n"
        f"## Haki researchowe (UŻYJ co najmniej jednego, NIE WYMYŚLAJ nowych)\n"
        f"{hook_lines}\n\n"
        f"## Co o nich wiemy z researchu\n"
        f"{rationale}\n\n"
        f"## KROK 1: Wybór ścieżki sprzedaży (offer_track)\n"
        f"Najpierw zdecyduj którą OFERTĘ Artmakera mailujesz dla tego leada.\n"
        f"Sugestia (nie musisz się zgadzać): {track_hint}\n"
        f"- 'b2b_panel' = panel B2B z magazynu PL, dostawa 24h, stała oferta. "
        f"Default. Najlepsze dla papierniczych, paint&sip, warsztatów dzieci, "
        f"szkół, mniejszych sklepów plastycznych.\n"
        f"- 'private_label' = produkcja w Chinach pod marką własną klienta. "
        f"Tylko gdy widać skalę / istniejącą markę / aspiracje brandingowe.\n"
        f"- 'both' = w jednym mailu wspomnieć obie. Użyj OSZCZĘDNIE: tylko gdy "
        f"lead jest pomiędzy. Zwykle lepiej skupić się na jednej.\n\n"
        f"## KROK 2: Cold mail do {lead.company_name}\n\n"
        f"### Struktura snippetów (każdy = jeden akapit, każdy krótki):\n"
        f"- subject: temat maila. Max 50 znaków. Format: pytanie/liczba/konkret. "
        f"  Test: jeśli zobaczyłbyś ten subject w skrzynce, otworzyłbyś bez "
        f"  wahania? Jak nie - przeformułuj.\n"
        f"- snippet1: pierwsze zdanie/dwa. MUSI nawiązać do konkretnego haka. "
        f"  Bez 'Dzień dobry'. Zacznij od mięsa - pytania, obserwacji, konkretu.\n"
        f"- snippet2: kim jesteś (krótko, 1 zdanie) i dlaczego piszesz "
        f"  AKURAT do nich (połącz to z hakiem). Max 2 zdania.\n"
        f"- snippet3: KONKRETNA oferta zgodna z wybraną offer_track:\n"
        f"  * b2b_panel: panel B2B Artmakera POD URL **https://b2b.sowins.pl** "
        f"    (MUSISZ podać ten URL w mailu jeśli wybierasz b2b_panel - to nasz konkretny adres, nie generic 'panel B2B'). "
        f"    Magazyn w PL, wysyłka w 24h, ceny hurtowe od producenta. "
        f"    Minimum logistyczne: 1000 zł netto na zamówienie. "
        f"    Dostawa GRATIS przy zamówieniach od minimum. "
        f"    NIE pisz 'bez minimum zamówienia' - to nieprawda. "
        f"    Konkretne kategorie produktów które ich dotyczą.\n"
        f"  * private_label: produkcja w naszych chińskich fabrykach pod ich "
        f"    specyfikację, własna marka, opakowania, 30-50% taniej niż polska "
        f"    hurtownia. Wspomnij MOQ tylko jeśli pasuje (300-1000 szt).\n"
        f"  * both: jedno zdanie o b2b_panel (z URL b2b.sowins.pl i wzmianką "
        f"    o minimum 1000 zł + gratis dostawa) + jedno zdanie 'a jeśli kiedyś "
        f"    chcielibyście rozwinąć własną markę - możemy też...'\n"
        f"- snippet4: opcjonalny social proof / liczba (np. 'Obsługujemy "
        f"  ponad 200 sklepów papierniczych w Polsce.'). Tylko jeśli AUTENTYCZNE. "
        f"  Lepsze null niż wymyślone. NIE WYMYŚLAJ liczb.\n"
        f"- snippet5: CTA-PYTANIE. Niski wysiłek dla odbiorcy. Np. "
        f"  'Wysłać dostęp do panelu B2B żeby Pani zerknęła?' albo "
        f"  'Otworzyłaby się Pani na 10 minut w czwartek po 14?'.\n\n"
        f"### Cały mail (snippet1+2+3+4?+5) MUSI mieć 70-130 słów. KRÓTKO.\n"
        f"### NIGDY nie używaj długiego myślnika ani średniego myślnika w żadnym snippecie. Tylko zwykły dywiz -.\n"
    )


def _suggest_track_hint(segment: str, monthly_volume: str) -> str:
    """Heuristic suggestion for which sales track suits this lead. The LLM
    has the final say in offer_track - this is just a starter hint."""
    if segment == "marka_wlasna":
        return "private_label (segment marka_wlasna - default Track A)."
    if segment in {"sklep_papierniczy", "paint_and_sip", "warsztaty_dzieci",
                   "animatorzy_eventy", "szkola_artystyczna"}:
        return f"b2b_panel (segment {segment} - typowo Track B)."
    if segment == "sklep_plastyczny":
        # Big shops can go private label, small ones panel B2B.
        if monthly_volume and any(c in monthly_volume for c in "5+") and "00" in monthly_volume:
            return (
                "both (sklep plastyczny z większym wolumenem - można "
                "zaproponować obie ścieżki)."
            )
        return "b2b_panel (sklep plastyczny - default Track B)."
    return "b2b_panel (default - bezpieczniej zacząć od panelu B2B)."


PERSONA_AND_RULES = """\
## Kim jesteś

Jesteś polskim handlowcem z 15-letnim doświadczeniem w branży importu z Chin
i sprzedaży hurtowej do sklepów detalicznych. Dorobiłeś się fortuny bo
piszesz maile, które ludzie naprawdę otwierają i czytają. Twoja przewaga:
brzmisz jak człowiek, nie jak generator. Konkret zamiast lania wody.
Polski biznes znasz od podszewki - wiesz jak rozmawia mały sklep w Łomży,
a jak właściciel sieci e-commerce w Warszawie. Dopasowujesz ton.

## Twoje zadanie teraz

Napisać cold mail B2B w imieniu Artmakera. Mail ma być TAK dobry, że odbiorca
otwiera go w 2 sekundy po dostaniu, czyta cały, i odpowiada w ciągu doby.

## ZASADY HARD (łamanie = mail trafia do spamu albo do kosza)

### Czego NIE WOLNO pisać

NIE WOLNO używać tych fraz (typowe AI/korpomowa, każdy je zna na pamięć):
- "Mam nadzieję, że ta wiadomość zastanie Pana/Panią w dobrym zdrowiu"
- "Pragnę zaproponować", "Chciałbym przedstawić", "Pozwolę sobie"
- "Z przyjemnością", "Z poważaniem", "Pozdrawiam serdecznie"
- "Korzystając z okazji", "Uprzejmie informuję", "Pragnę poinformować"
- "Rzucić światło na", "Otworzyć drzwi do", "W dzisiejszych czasach"
- "Rewolucyjny", "Innowacyjny", "Wyjątkowy", "Unikatowy", "Najwyższej jakości"
- "Dynamicznie rozwijający się", "Lider w branży", "Synergii"
- "Skłaniam się do", "Pewnie się Pan/Pani zastanawia"
- Otwarcie maila od "Dzień dobry," (typowe AI; lepiej od konkretu lub "Cześć")

NIE WOLNO używać tych znaków (każdy AI-detektor je łapie):
- DŁUGI MYŚLNIK em-dash "—" (Alt+0151) - ZAKAZANE, używaj zwykłego "-"
- ŚREDNI MYŚLNIK en-dash "–" (Alt+0150) - ZAKAZANE, używaj zwykłego "-"
- Cudzysłowy typograficzne ("..."): tylko proste "..." albo '...'
- Emoji w tekście maila (ALE w subject MOŻESZ jedno strategicznie umieścić)
- Wykrzykniki w body (max 0; w subject max 1, jeśli pasuje)

### Co MUSISZ pisać

1. **Krótkie zdania.** Średnio 10-14 słów. Najwyżej 18.
2. **Personalny otwór.** snippet1 MUSI nawiązać do konkretnego haka z researchu
   (cytuj/parafrazuj coś co rzeczywiście jest na ich stronie). Zacznij tak,
   żeby od pierwszego zdania wiedzieli że to NIE masówka.
3. **Wartość w liczbach.** Konkretne procenty oszczędności, ilości, terminy.
   Nie "atrakcyjne ceny" tylko "30-40% taniej niż polska hurtownia".
4. **CTA jako pytanie.** Zamiast "Czekam na odpowiedź" - "Otworzy Pan 10 minut
   we wtorek po 14?" albo "Wysłać Państwu cennik na sztalugi 60x80?"
5. **Polska forma.** Pan/Pani jeśli decydent jest "po nazwisku" w researchu.
   Po imieniu (np. Marek, Kasia) jeśli kontakt jest podany imieniem.
   Jeśli kontaktu brak - bezosobowo, do firmy ("Państwa sklep", "Wasza oferta").
6. **Naturalny ton.** Możesz użyć kolokwializmów ("krótko", "tak konkretnie",
   "rzucam temat", "z mojej strony"). Mail ma brzmieć jak napisany szybko
   przez człowieka, nie wypolerowany przez bota.
7. **Sygnatura prosta.** Bez "Z poważaniem". Po prostu imię + Artmaker.
   snippet5 zawiera CTA-pytanie. Nie pisz sygnatury w snippetach - zostawiamy ją systemowi.

### Subject - to się ZA NAJWIĘCEJ liczy

Subject decyduje o open-rate. ZASADY:
- Max 50 znaków (idealnie 35-45). Krótszy = lepszy open-rate.
- BEZ "Oferta:", "Propozycja współpracy", "Zapytanie ofertowe" - to filtry spamu.
- Najlepsze formaty:
  - Pytanie odwołujące się do ich biznesu: "Skąd bierzecie płótna do {firma}?"
  - Konkretna liczba intrygująca: "300 płócien miesięcznie?"
  - Wzmianka o ich konkurencie albo kategorii: "Cennik dla sklepów plastycznych w Warszawie"
  - Krótka korzyść: "30-40% taniej na farby akrylowe"
- Subject MOŻE zawierać nazwę firmy adresata (boost personalizacji).
- ZAKAZ używania słów spam-trigger: "darmowe", "okazja", "tylko dziś", "100%", "promocja", "rabat".
- Pierwsza litera duża, reszta małymi (chyba że nazwa własna). Bez ALL CAPS.
"""


def _build_system_prompt() -> str:
    """System prompt: brand context + persona + hard anti-AI rules + voice anchor."""
    examples = _load_few_shot_examples()
    examples_block = (
        f"\n\n## Przykłady stylu autora (trzymaj się tego brzmienia)\n{examples}"
        if examples
        else ""
    )
    return (
        f"{BRAND_CONTEXT}\n\n"
        f"{PERSONA_AND_RULES}\n\n"
        "Zwracasz wyłącznie poprawny JSON zgodny ze schematem. Każdy snippet "
        "to jeden krótki akapit. Nie powtarzaj brand context'u w mailu - "
        "odbiorca chce wiedzieć co ma z tego ON, nie kim jesteśmy."
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
        temperature=DRAFT_TEMPERATURE,
    )

    # Scrub AI artifacts (em-dash, smart quotes, clichés) before persisting.
    payload = EmailDraftPayload(
        offer_track=payload.offer_track,
        subject=_strip_ai_artifacts(payload.subject) or payload.subject,
        snippet1=_strip_ai_artifacts(payload.snippet1) or payload.snippet1,
        snippet2=_strip_ai_artifacts(payload.snippet2) or payload.snippet2,
        snippet3=_strip_ai_artifacts(payload.snippet3) or payload.snippet3,
        snippet4=_strip_ai_artifacts(payload.snippet4),
        snippet5=_strip_ai_artifacts(payload.snippet5) or payload.snippet5,
    )

    full_preview = _assemble_preview(payload)
    cost = estimate_cost_usd(provider, model, usage)
    logger.bind(source="generate").info(
        f"Draft generated for lead #{lead_id} via {provider}/{model}; "
        f"~${cost} usd; track={payload.offer_track}; subject={payload.subject!r}"
    )

    with SessionLocal() as session:
        draft = EmailDraft(
            lead_id=lead_id,
            template_variant=f"cold_v1_{payload.offer_track}",
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
