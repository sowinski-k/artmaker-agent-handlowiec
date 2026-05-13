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
from core.llm import parse_structured
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
# Co tu jest: typowe AI/korpo-frazy ktore AI-detektory (Sift, Substance.AI) lapia
# w 200ms, oraz typowe spam-trigger phrases.
_AI_CLICHES = [
    # Klasyki AI openings
    r"Mam nadzieję, że ta wiadomość zastanie [^.,!?\n]*[.,!?]?\s*",
    r"Mam nadzieję, że [^.,!?\n]*?dobrym zdrowiu[.,!?]?\s*",
    r"Mam nadzieję, że (?:list|mail|wiadomość)[^.,!?\n]*[.,!?]?\s*",
    # Korpo-otwarcia
    r"Szanowni Państwo[,.!]?\s*",
    r"Szanowny Panie[^.,!?\n]*[,.!]?\s*",
    r"Szanowna Pani[^.,!?\n]*[,.!]?\s*",
    # Sztywne formaly
    r"Pozdrawiam serdecznie[,.!]?\s*",
    r"Z wyrazami szacunku[,.!]?\s*",
    r"Z poważaniem[,.!]?\s*",
    r"Łączę wyrazy szacunku[,.!]?\s*",
    # AI-templated propositions
    r"Pragnę (?:poinformować|zaproponować|przedstawić|zainteresować)[^.,!?\n]*[.,!?]?\s*",
    r"Chciał(?:a)?bym (?:zaproponować|przedstawić|zaprezentować|zainteresować)[^.,!?\n]*[.,!?]?\s*",
    r"Pozwolę sobie (?:zaproponować|przedstawić|zwrócić)[^.,!?\n]*[.,!?]?\s*",
    r"Pozwalam sobie[^.,!?\n]*[.,!?]?\s*",
    r"Mogę (?:Państwu|Pani|Panu) (?:zaproponować|przedstawić)[^.,!?\n]*[.,!?]?\s*",
    r"Korzystając z okazji[^.,!?\n]*[.,!?]?\s*",
    r"Uprzejmie informuję[^.,!?\n]*[.,!?]?\s*",
    r"Pewnie się Pan(?:i)? zastanawia[^.,!?\n]*[.,!?]?\s*",
    # Buzzwords - korpo PR
    r"\brewolucyjn[ya]\w*\b",
    r"\binnowacyjn[ya]\w*\b",
    r"\bunikatow[ya]\w*\b",
    r"\bwyjątkow[ya]\w*\b",
    r"\bnajwyższej jakości\b",
    r"\bdynamicznie (?:rozwijając|działając)\w*\b",
    r"\blider(?:em|a)? (?:w|na) (?:branż|branz|rynk)\w+\b",
    r"\bsynergi[iąe]\b",
    r"\bw dzisiejszych czasach\s+",
    r"\bz przyjemnością\b",
    r"\brzucić światło na\b",
    r"\botworzyć drzwi do\b",
    r"\błącze w sobie\b",
    # Generic auto-opening
    r"(?:^|\n)\s*Dzień dobry[,!]\s*",
]
_AI_CLICHE_PATTERN = re.compile("|".join(_AI_CLICHES), re.IGNORECASE | re.MULTILINE)


def _strip_ai_artifacts(text: str | None) -> str | None:
    """Punctuation + cliche scrub. Idempotent.

    - Replaces em-dash / en-dash / smart quotes with ASCII equivalents.
    - Removes blacklisted AI/corpo phrases the model occasionally smuggles in.
    - Collapses runs of spaces and trims edges.
    - Czysci podwojne ".." po usunieciu frazy (np "Pragne X. Tresc." -> ". Tresc.")

    Returns the cleaned string, or None if input was None/empty.
    """
    if not text:
        return text
    out = text
    for src, dst in _PUNCT_REPLACEMENTS.items():
        out = out.replace(src, dst)
    out = _AI_CLICHE_PATTERN.sub("", out)
    # Po usunieciu frazy zaczynajacej zdanie zostaje czasem dziwny ". " na poczatku
    out = re.sub(r"^\s*[.,;:!?]+\s*", "", out)
    # Podwojne kropki/przecinki ktore zostaly po cieciu fraz
    out = re.sub(r"\s*\.\s*\.\s*", ". ", out)
    out = re.sub(r"\s*,\s*,\s*", ", ", out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


# ---- Anti-slop validation: hard guardrails post-generation -----------------
#
# Idea: po LLM call i po _strip_ai_artifacts, sprawdz czy draft spelnia
# nasze invarianty. Zwroc liste warningow (puste = OK). Caller moze:
#   - zlogowac warnings i przepuscic (warn)
#   - rzucic ValueError (hard validation - retry generation)

_POLISH_DIACRITICS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_MAX_SENTENCE_WORDS = 22
_MAX_SUBJECT_CHARS = 50


def _split_sentences(text: str) -> list[str]:
    """Prosty splitter zdan - bez external lib. Dziele na '.', '!', '?'."""
    if not text:
        return []
    # Nie tnie skrotow typu 'np.' / 'tj.' (po malej literze)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZŁĆŻŚĘĄŃÓ])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _check_polish_diacritics(text: str | None) -> bool:
    """Czy tekst zawiera POLSKIE znaki? Mail po polsku bez diakrytykow
    wyglada jak masowka z translatora - red flag dla spam-filtrow."""
    if not text:
        return True  # puste OK
    if len(text) < 20:
        return True  # za krotkie zeby sensownie sprawdzac
    return any(c in _POLISH_DIACRITICS for c in text)


def _check_forma_consistency(text: str) -> bool:
    """Sprawdz spojnosc formy zwracania sie: PANSTWO vs WY.

    Mieszanie 'u Panstwa' z 'u Was' to klasyczny AI-tell + niespojnosc
    znana z google translate. Wykrywamy oba warianty w jednym tekscie.
    """
    if not text:
        return True
    has_panstwo = bool(re.search(r"\b(?:Pań?stw[ao]|u Państwa|Państwa)\b", text, re.IGNORECASE))
    has_wy = bool(re.search(r"\b(?:Wasz\w*|u Was|Wam|Was(?:i|e|y)?)\b", text))
    return not (has_panstwo and has_wy)


def validate_draft(payload: "EmailDraftPayload") -> list[str]:
    """Sprawdz draft po LLM + scrub. Zwroc liste warningow.

    Kazdy warning to ostrzezenie - caller decyduje czy retry. Hard
    failures (subject za dlugi, brak polskich znakow w body) sa
    powodem do retry generation z innym promptem/seedem.
    """
    warnings: list[str] = []

    # Subject - hard limit
    if payload.subject and len(payload.subject) > _MAX_SUBJECT_CHARS:
        warnings.append(
            f"subject za dlugi ({len(payload.subject)} znakow, max {_MAX_SUBJECT_CHARS})"
        )

    # Wszystkie snippet'y - check dlugosci zdan
    snippets = [
        ("snippet1", payload.snippet1),
        ("snippet2", payload.snippet2),
        ("snippet3", payload.snippet3),
        ("snippet4", payload.snippet4),
        ("snippet5", payload.snippet5),
    ]
    body_concat_parts: list[str] = []
    for name, snip in snippets:
        if not snip:
            continue
        body_concat_parts.append(snip)
        for sentence in _split_sentences(snip):
            words = sentence.split()
            if len(words) > _MAX_SENTENCE_WORDS:
                warnings.append(
                    f"{name}: zdanie ma {len(words)} slow (max {_MAX_SENTENCE_WORDS}): "
                    f"{sentence[:80]}..."
                )

    full_body = " ".join(body_concat_parts)

    # Polskie diakrytyki w body (subject moze byc bardziej skrajny)
    if not _check_polish_diacritics(full_body):
        warnings.append("body bez polskich znakow diakrytycznych - wyglada na masowke")

    # Spojnosc formy
    if not _check_forma_consistency(full_body):
        warnings.append("body miesza forme 'Panstwo' i 'Wy/Was' - wybierz jedna")

    # Track A priority check: jesli offer_track=both, snippet3 powinien
    # zaczynac od Track A signalow przed Track B (heurystyka)
    if payload.offer_track == "both" and payload.snippet3:
        idx_pl = _earliest_index(payload.snippet3.lower(),
                                  ["private", "produkc", "fabryk", "marka wlasna", "marka własna",
                                   "własn", "wlasn", "pod wasza", "pod państwa marką", "moq"])
        idx_b2b = _earliest_index(payload.snippet3.lower(),
                                   ["b2b.sowins", "panel b2b", "magazyn", "24h", "od reki", "od ręki"])
        if idx_pl is not None and idx_b2b is not None and idx_b2b < idx_pl:
            warnings.append(
                "offer_track=both ale Track B (panel B2B) wymieniony PRZED Track A "
                "(private_label) w snippet3 - filozofia 'Plan B to plan B' wymaga "
                "odwrotnej kolejnosci"
            )

    return warnings


def _earliest_index(text: str, needles: list[str]) -> int | None:
    """Helper: najnizszy index pierwszego trafienia z listy needles."""
    indices = [text.find(n) for n in needles if n]
    indices = [i for i in indices if i >= 0]
    return min(indices) if indices else None


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

    # Sygnały skali - wpływają na sugestie Track A vs B (commit Track A priority)
    score_breakdown = rd.get("score") or {}
    bulk_potential = score_breakdown.get("bulk_potential")
    scale_score = score_breakdown.get("scale")

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

    # Track recommendation hint - DOMYSLNIE 'both' z preferencja Track A.
    # LLM has final say, ale prompt ma jasna preferencje (commit Track A priority).
    track_hint = _suggest_track_hint(segment, monthly, bulk_potential, scale_score)

    return (
        f"## Lead do napisania\n"
        f"Firma: {lead.company_name}\n"
        f"Strona: {lead.website or '(brak)'}\n"
        f"Miasto: {lead.city or '(brak)'}\n"
        f"Segment: {segment}\n"
        f"Kontakt: {contact}\n"
        f"Email do wysyłki: {lead.email or '(brak)'}\n"
        f"Szacunkowy wolumen B2B: {monthly}\n"
        f"Sygnaly skali (z research): bulk_potential={bulk_potential}, scale={scale_score}\n"
        f"Ton: {tone_hint}\n\n"
        f"## Haki researchowe (UŻYJ co najmniej jednego, NIE WYMYŚLAJ nowych)\n"
        f"{hook_lines}\n\n"
        f"## Co o nich wiemy z researchu\n"
        f"{rationale}\n\n"
        f"## KROK 1: Wybór ścieżki sprzedaży (offer_track)\n"
        f"FILOZOFIA SPRZEDAZY ARTMAKERA: Track A (private_label) to nasz PLAN A. "
        f"Track B (b2b_panel) to PLAN B - 'cos od reki z magazynu'. Domyslnie "
        f"proponujemy OBIE opcje, ale z preferencja Track A jako sciezki "
        f"glownej (private label, marka wlasna, produkcja w Chinach - to dla "
        f"klienta WIEKSZY biznes dlugoterminowy i wieksza wartosc dla nas).\n\n"
        f"Sugestia heurystyki: {track_hint}\n\n"
        f"Definicje track:\n"
        f"- 'private_label' (Track A, PREFEROWANY) = produkujemy farby, "
        f"  sztalugi, plotna, akcesoria DIY w naszych zakontraktowanych "
        f"  fabrykach w Chinach pod specyfikacje klienta. Wlasna marka, "
        f"  personalizowane opakowania, etykiety, 30-50% taniej niz polska "
        f"  hurtownia bo omijamy 2-3 posrednikow. MOQ 300-1000 szt, "
        f"  lead time 4-8 tygodni produkcji + transport.\n"
        f"- 'b2b_panel' (Track B, PLAN B) = stala oferta z naszego magazynu "
        f"  w Polsce, dostawa w 24h, ceny hurtowe. Panel pod "
        f"  https://b2b.sowins.pl. Minimum logistyczne 1000 zl netto, "
        f"  dostawa GRATIS od tego minimum. NIE pisz 'bez minimum'.\n"
        f"- 'both' (DEFAULT dla wiekszosci leadow) = w jednym mailu wymien "
        f"  OBIE opcje. Kolejnosc: NAJPIERW Track A jako glowna propozycja "
        f"  (budowanie wlasnej marki + wieksze marze), POTEM Track B jako "
        f"  'a jak czegos potrzebujecie OD RAZU z magazynu, to mamy panel B2B'. "
        f"  Track A jako rozwoj/strategia, Track B jako szybkie wejscie/uzupelnienie.\n\n"
        f"## KROK 2: Cold mail do {lead.company_name}\n\n"
        f"### Struktura snippetów (każdy = jeden akapit, każdy krótki):\n"
        f"- subject: temat maila. Max 50 znaków. Format: pytanie/liczba/konkret. "
        f"  Test: jeśli zobaczyłbyś ten subject w skrzynce, otworzyłbyś bez "
        f"  wahania? Jak nie - przeformułuj.\n"
        f"- snippet1: pierwsze zdanie/dwa. MUSI nawiązać do konkretnego haka. "
        f"  Bez 'Dzień dobry', bez 'Szanowni Panstwo'. Zacznij od mięsa - "
        f"  pytania, obserwacji, konkretu z ich strony.\n"
        f"- snippet2: kim jesteś (krótko, 1 zdanie) i dlaczego piszesz "
        f"  AKURAT do nich (połącz to z hakiem). Max 2 zdania.\n"
        f"- snippet3: KONKRETNA oferta zgodna z wybraną offer_track:\n"
        f"  * private_label: produkcja w naszych chinskich fabrykach pod ich "
        f"    specyfikacje + wlasna marka, opakowania, 30-50% taniej niz "
        f"    polska hurtownia. Wspomnij MOQ tylko jesli realnie pasuje "
        f"    (300-1000 szt). Konkretne kategorie produktow ktore moglibysmy "
        f"    dla nich produkowac (na podstawie ich oferty - hooks).\n"
        f"  * b2b_panel: panel B2B Artmakera POD URL **https://b2b.sowins.pl** "
        f"    (MUSISZ podac ten URL w mailu - to nasz konkretny adres, "
        f"    nie generic 'panel B2B'). Magazyn w PL, wysylka w 24h, "
        f"    ceny hurtowe od producenta. Minimum logistyczne: 1000 zl "
        f"    netto na zamowienie. Dostawa GRATIS przy zamowieniach "
        f"    od minimum. NIE pisz 'bez minimum zamowienia'.\n"
        f"  * both: NAJPIERW 1-2 zdania o private_label (produkcja pod ich "
        f"    marka w Chinach, 30-50% taniej, indywidualne wyceny, zbudowanie "
        f"    wlasnej marki), POTEM 1 zdanie o b2b_panel jako alternatywie "
        f"    'na juz' (URL b2b.sowins.pl, magazyn PL, dostawa 24h, "
        f"    minimum 1000 zl + gratis transport). Ton: Track A to plan, "
        f"    Track B to dodatek/uzupelnienie. NIE odwrotnie.\n"
        f"- snippet4: opcjonalny social proof / liczba (np. 'Obsługujemy "
        f"  ponad 200 sklepów papierniczych w Polsce.'). Tylko jeśli AUTENTYCZNE. "
        f"  Lepsze null niż wymyślone. NIE WYMYŚLAJ liczb.\n"
        f"- snippet5: CTA-PYTANIE. Niski wysilek dla odbiorcy. Przyklady:\n"
        f"  - 'Podeslac kilka realizacji private label ktore robilismy "
        f"    w zeszlym roku?'\n"
        f"  - 'Otworzyloby sie Panstwu 15 minut w czwartek po 14 na krotka "
        f"    rozmowe?'\n"
        f"  - 'Mam wstepna wycene produkcyjna dla 500 sztuk - wyslac do "
        f"    porownania z tym co teraz placicie?'\n\n"
        f"### Cały mail (snippet1+2+3+4?+5) MUSI mieć 80-140 słów. KRÓTKO.\n"
        f"### NIGDY nie używaj długiego myślnika ani średniego myślnika w żadnym snippecie. Tylko zwykły dywiz -.\n"
    )


def _parse_volume_pln(volume_str: str | None) -> int | None:
    """Wyciagnij DOLNA granica kwoty z estimated_monthly_volume.

    '300-800 PLN'   -> 300
    '2000+ PLN'     -> 2000
    '5000-10000'    -> 5000
    'kilkaset zlotych' / null / nieparsowalne -> None
    """
    if not volume_str:
        return None
    # Znajdz pierwsza liczbe w stringu (z ewentualnymi tysiacami)
    m = re.search(r"(\d[\d\s]{1,8})", volume_str)
    if not m:
        return None
    try:
        return int(m.group(1).replace(" ", ""))
    except ValueError:
        return None


def _suggest_track_hint(
    segment: str,
    monthly_volume: str | None,
    bulk_potential: float | None,
    scale: float | None,
) -> str:
    """Track suggestion. NOWE FILOZOFICZNE PODEJSCIE (commit ten):

    Default = 'both' z preferencja Track A (private_label). Track B jest
    PLANEM B, nie planem A. Track A ma byc proponowany WSZEDZIE GDZIE JEST
    POTENCJAL - czyli wszedzie gdzie nie wyklucza tego natura biznesu.

    Reguly w kolejnosci checking:
    1. marka_wlasna -> private_label (segment z definicji = Track A)
    2. bulk_potential >= 1.5 LUB scale >= 1.5 LUB volume >= 2000zl
       -> 'both' z mocnym Track A first (skalowalny biznes)
    3. paint_and_sip/warsztaty/animatorzy (typowa konsumpcja od reki)
       -> 'both' ale Track B pierwsze (wewn. zuzycie), Track A wspomniany
        jako opcja na przyszlosc (zestawy edycyjne, marka warsztatu)
    4. sklep_papierniczy / sklep_plastyczny / szkola / inne
       -> domyslnie 'both', Track A first (private label = wiekszy biznes)

    LLM zawsze ma final say - to suggestion not mandate.
    """
    if segment == "marka_wlasna":
        return (
            "private_label (segment marka_wlasna - z definicji Track A). "
            "Track B mozesz wspomniec ZWIEZLE jako 'a jak chcecie cos OD REKI z magazynu PL "
            "do uzupelnienia oferty, mamy panel'."
        )

    vol_pln = _parse_volume_pln(monthly_volume)
    big_signal = (
        (bulk_potential is not None and bulk_potential >= 1.5)
        or (scale is not None and scale >= 1.5)
        or (vol_pln is not None and vol_pln >= 2000)
    )

    if big_signal:
        return (
            "both - Track A (private_label) PIERWSZE bo widac potencjal skali "
            f"(bulk_potential={bulk_potential}, scale={scale}, vol={monthly_volume!r}). "
            "Track B wspomniany na koncu jako 'a jak chcecie cos juz teraz z magazynu'."
        )

    if segment in {"paint_and_sip", "warsztaty_dzieci", "animatorzy_eventy"}:
        return (
            f"both - dla segmentu {segment} Track B (b2b_panel) jest naturalny "
            "(konsumpcyjne zuzycie farb/platen), ALE Track A wspominamy zawsze "
            "(zestawy startowe z ich logo, marka warsztatu, gift-boxy na eventy). "
            "Track A jako mocna mozliwosc rozwoju, nie afterthought."
        )

    if segment == "szkola_artystyczna":
        return (
            "both - szkoly maja oba zastosowania: Track B (regularne uzupelnianie "
            "materialow), Track A (zestawy edukacyjne z brandingiem szkoly, "
            "merch dla absolwentow). Wymien obie, prefer Track A jako 'rozwoj'."
        )

    # sklep_plastyczny / sklep_papierniczy / inne - domyslnie 'both', Track A first
    return (
        f"both - dla segmentu {segment} ZAWSZE proponuj OBIE opcje. "
        "Track A (private_label) PIERWSZY: produkujemy pod ich marka w Chinach, "
        "30-50% taniej niz polska hurtownia, zbudowanie wlasnej marki. "
        "Track B (b2b_panel) jako szybkie wejscie 'na juz' / uzupelnienie asortymentu."
    )


PERSONA_AND_RULES = """\
## Kim jesteś

Jesteś polskim handlowcem z 20-letnim doświadczeniem w branży importu z Chin
i sprzedaży hurtowej do sklepów detalicznych. Sam zaczynałeś jako mały
sklepik plastyczny, potem otworzyłeś hurtownię, potem zakontraktowałeś
fabryki w Chinach. Wiesz JAK wyglądają obie strony. Piszesz maile, ktore
ludzie otwierają i czytają - bo zaczynasz od ich biznesu, nie od swojego.
Twoj wlasciciel zwraca uwage na kazdy szczegol - jak brzmi mail, czy nie
ma typowych AI-tellow, czy odbiorca poczuje ze pisze do niego CZLOWIEK
a nie generator.

## FILOZOFIA SPRZEDAZY ARTMAKERA (krytyczne)

Mamy dwie sciezki. Track A = private label / produkcja w Chinach pod
marka klienta. Track B = panel B2B z magazynu PL, dostawa 24h.

**Plan A = Track A. Plan B = Track B. NIE odwrotnie.**

Wiekszosc cold maili w naszej branzy proponuje TYLKO Track B - "kupcie
od nas hurt, wysylamy". To zostawia 80% wartosci na stole. My idziemy
inaczej:

- Domyslnie wymieniamy OBIE opcje
- ZAWSZE Track A pierwszy (wieksze biznes, wieksza marza, wieksza
  wartosc dla klienta)
- Track B jako "a jak czegos potrzebujecie OD RAZU z magazynu, mamy
  panel"
- TYLKO marka_wlasna dostaje WYLACZNIE Track A
- TYLKO bardzo male single-shop bez aspiracji moze dostac tylko Track B

To rozroznia nas od kazdego "hurtownika" co bombarduje katalogiem.
My pomagamy zbudowac IM marke, oni placa nam za produkcje. To inny
poziom rozmowy.

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
5. **JEDNA forma w CAŁYM mailu - Państwo (B2B formal).** Bezwzględnie spójnie
   od subject do CTA. NIGDY nie mieszaj z "Wy/Wasz/Wasze/Wam/Was". Pisz:
   - "Państwa sklep", "Państwa oferta", "u Państwa", "Państwa klienci".
   - NIE: "Wasz sklep", "Wasza oferta", "u Was", "Waszych klientów".
   Jeśli znamy nazwisko/imię osoby kontaktowej -> dodajemy "Panie Tomaszu" /
   "Pani Anno" w otwarciu, ale resztą maila nadal "Państwo". Mieszanie
   Pan/Państwo to OK; mieszanie Państwo/Wy to NIE OK.
6. **POLSKIE ZNAKI obowiązkowe.** Subject ORAZ całe body MUSZĄ mieć polskie
   diakrytyki: ą ć ę ł ń ó ś ź ż. Nigdy "produktow" - zawsze "produktów".
   Nigdy "wspolpraca" - zawsze "współpraca". To MAIL DO POLAKA, brak ogonków
   wygląda jak masówka z translate.
7. **Naturalny ton.** Możesz użyć kolokwializmów ("krótko", "tak konkretnie",
   "rzucam temat", "z mojej strony"). Mail ma brzmieć jak napisany szybko
   przez człowieka, nie wypolerowany przez bota.
8. **Sygnatura prosta.** Bez "Z poważaniem". Po prostu imię + Artmaker.
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


def _call_with_retry(
    *,
    provider: str,
    model: str,
    system: str,
    user: str,
    max_tokens_attempts: tuple[int, ...] = (4096, 6144),
) -> "EmailDraftPayload":
    """Wywołaj LLM z eskalacją max_tokens przy parse failure.

    Gemini 3.x preview z thinking budget czasem dochodzi do limitu max_tokens
    i ucina JSON w środku stringa (Pydantic validation error: Invalid JSON EOF).
    Retry'ujemy z większym max_tokens zanim podniesiemy wyjątek.
    """
    last_exc: Exception | None = None
    for attempt_idx, mt in enumerate(max_tokens_attempts):
        try:
            payload, _usage = parse_structured(
                provider=provider, model=model,
                system=system, user=user,
                output_schema=EmailDraftPayload,
                max_tokens=mt,
                temperature=DRAFT_TEMPERATURE,
            )
            return payload
        except Exception as exc:
            last_exc = exc
            # Retry tylko dla parse / json errors. Inne (np. brak klucza) niech idą.
            msg = str(exc).lower()
            if "json" not in msg and "validation" not in msg and "parse" not in msg:
                raise
            logger.bind(source="generate").warning(
                f"Draft parse failure z max_tokens={mt} (attempt {attempt_idx+1}/"
                f"{len(max_tokens_attempts)}): {exc}. Retry z większym budżetem..."
            )
    # Wszystkie próby spasowały
    raise RuntimeError(
        f"Draft generation padł po {len(max_tokens_attempts)} próbach. "
        f"Ostatni błąd: {last_exc}"
    )


def generate_draft_for_lead(
    lead_id: int,
    *,
    provider: str | None = None,
    model: str | None = None,
    workspace_id: int | None = None,
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

    # 2000 tokens to dla Gemini 3.x preview za mało - thinking budget zjada
    # część puli i JSON się ucina w środku stringa (validation error EOF).
    # 4096 daje komfortowy zapas dla 70-130 słów body + sub + offer_track.
    # Retry z 6144 jeśli i tak się posypie.
    payload = _call_with_retry(
        provider=provider, model=model, system=system, user=user,
        max_tokens_attempts=(4096, 6144),
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

    # Hard validation - ostrzezenia po scrub. Na razie tylko logujemy (soft mode);
    # jak bedzie problem na produkcji mozemy podlaczyc retry na warning != [].
    warnings = validate_draft(payload)
    if warnings:
        for w in warnings:
            logger.bind(source="generate").warning(
                f"Draft #lead={lead_id} validation: {w}"
            )

    full_preview = _assemble_preview(payload)
    logger.bind(source="generate").info(
        f"Draft generated for lead #{lead_id} via {provider}/{model}; "
        f"track={payload.offer_track}; subject={payload.subject!r}"
    )

    with SessionLocal() as session:
        draft = EmailDraft(
            workspace_id=workspace_id,
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


SNIPPET_INSTRUCTIONS = {
    "subject": (
        "Wygeneruj alternatywny temat maila (subject). Max 50 znaków. "
        "Format pytanie/liczba/konkret. Nie używaj 'Oferta:', 'Propozycja'. "
        "Test: czy w skrzynce ten subject się otwiera bez zastanowienia?"
    ),
    "snippet1": (
        "Wygeneruj alternatywne otwarcie maila. MUSI nawiązać do konkretnego "
        "haka z researchu (dostarczonego niżej). Bez 'Dzień dobry'. Zacznij od "
        "konkretu - pytanie, obserwacja, liczba. Max 2 zdania."
    ),
    "snippet2": (
        "Wygeneruj alternatywny most do oferty - kim jesteś (1 zdanie) i czemu "
        "piszesz akurat do nich. Max 2 zdania, naturalny ton."
    ),
    "snippet3": (
        "Wygeneruj alternatywną konkretną ofertę zgodną z offer_track (b2b_panel "
        "= panel B2B z magazynu, dostawa 24h, minimum 1000 zł, gratis transport, "
        "URL b2b.sowins.pl; private_label = produkcja Chiny + MOQ 300-1000szt). "
        "Liczby, terminy. Bez 'rewolucyjny', 'wyjątkowy', 'innowacyjny'."
    ),
    "snippet4": (
        "Wygeneruj alternatywny social proof / konkretną liczbę. Tylko AUTENTYCZNE - "
        "lepiej zwróć pusty string jeśli nic prawdziwego nie ma sensu wpisać."
    ),
    "snippet5": (
        "Wygeneruj alternatywne CTA. MUSI być pytaniem z niskim wysiłkiem dla "
        "odbiorcy. Np. 'Wysłać cennik?', 'Otworzysz 10 min w piątek po 14?'."
    ),
}


def regenerate_snippet(
    draft_id: int,
    snippet_name: str,
    *,
    user_instruction: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """Wygeneruj alternatywną wersję jednego konkretnego snippetu.

    NIE zapisuje do DB - zwraca nowy tekst, caller decyduje czy podstawić.
    Pozwala userowi w GUI klikać 'inna wersja' aż znajdzie coś co mu pasuje.

    Args:
        draft_id: ID istniejącego draftu (do kontekstu - hooki, segment leada)
        snippet_name: jeden z 'subject', 'snippet1'..'snippet5'
        user_instruction: opcjonalna instrukcja od usera, np. 'krócej',
            'bardziej formalnie', 'wspomnij o ich Instagramie'
        provider, model: jak zwykle, default z settings

    Returns: pojedynczy string (nowy tekst snippetu, scrubbed z AI artifacts).
    """
    if snippet_name not in SNIPPET_INSTRUCTIONS:
        raise ValueError(
            f"snippet_name={snippet_name!r} - dozwolone: {list(SNIPPET_INSTRUCTIONS)}"
        )

    provider = (provider or settings.llm_provider).lower()
    if provider == "anthropic":
        model = model or settings.anthropic_model
    elif provider == "gemini":
        model = model or settings.gemini_model

    with SessionLocal() as session:
        draft = session.get(EmailDraft, draft_id)
        if draft is None:
            raise ValueError(f"Draft #{draft_id} nie istnieje.")
        lead = session.get(Lead, draft.lead_id)
        if lead is None:
            raise ValueError(f"Lead #{draft.lead_id} dla draftu #{draft_id} zniknął.")

        # Kontekst: aktualny stan całego maila + hooki researchu
        rd = lead.research_data or {}
        hooks = rd.get("concrete_hooks") or []
        hook_lines = "\n".join(
            f"- {h.get('text', '').strip()}" for h in hooks if h.get("text")
        ) or "(brak haków)"
        current_snippets = {
            "subject": draft.subject or "",
            "snippet1": draft.snippet1 or "",
            "snippet2": draft.snippet2 or "",
            "snippet3": draft.snippet3 or "",
            "snippet4": draft.snippet4 or "",
            "snippet5": draft.snippet5 or "",
        }
        current_block = "\n".join(
            f"  [{k}{' <- DO ZMIANY' if k == snippet_name else ''}]: {v}"
            for k, v in current_snippets.items()
        )
        company = lead.company_name

    # Reuse istniejący persona+rules system prompt, plus szczególna instrukcja
    base_system = _build_system_prompt()
    specific = SNIPPET_INSTRUCTIONS[snippet_name]

    user_clause = (
        f"\nDodatkowa instrukcja od użytkownika: {user_instruction.strip()}\n"
        if user_instruction and user_instruction.strip() else ""
    )

    user_prompt = (
        f"## Lead\n"
        f"Firma: {company}\n"
        f"Haki researchowe:\n{hook_lines}\n\n"
        f"## Aktualny stan maila\n"
        f"{current_block}\n\n"
        f"## Twoje zadanie\n"
        f"{specific}\n"
        f"{user_clause}"
        f"\nZwróć WYŁĄCZNIE nowy tekst dla {snippet_name} jako jednolite pole 'text'. "
        f"Bez metadanych, bez wyjaśnień, bez nazwy snippetu w wartości."
    )

    # Maleńka pydantic struct dla single-field outputu
    class SnippetOnly(BaseModel):
        text: str = Field(description="Nowy tekst snippetu (sam tekst, nic więcej)")

    payload, _usage = parse_structured(
        provider=provider, model=model,
        system=base_system, user=user_prompt,
        output_schema=SnippetOnly,
        max_tokens=2048,
        temperature=DRAFT_TEMPERATURE,
    )
    new_text = _strip_ai_artifacts(payload.text) or payload.text
    logger.bind(source="generate").info(
        f"Regenerated {snippet_name} for draft #{draft_id}: {new_text[:60]!r}..."
    )
    return new_text


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
    workspace_id: int | None = None,
) -> tuple[int, int]:
    """Bulk-generate drafts for every researched lead without an active draft.

    Returns (made, failed). Skips leads with score < min_score.
    """
    with SessionLocal() as session:
        q = select(Lead.id).where(
            Lead.status == LeadStatus.RESEARCHED.value,
            Lead.score >= min_score,
        )
        if workspace_id is not None:
            q = q.where(Lead.workspace_id == workspace_id)
        candidate_ids = session.execute(q).scalars().all()

    made, failed = 0, 0
    for lead_id in candidate_ids:
        if is_stopped():
            logger.bind(source="generate").warning("STOP.txt detected, halting bulk generate.")
            break
        try:
            generate_draft_for_lead(lead_id, provider=provider, model=model, workspace_id=workspace_id)
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
