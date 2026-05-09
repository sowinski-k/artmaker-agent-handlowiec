import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow `streamlit run gui/app.py` to import the `core` package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from agent.discovery import (
    ApifyAllegroSource,
    ApifyLinkedInSource,
    ApifySource,
    CSVSource,
    DiscoveredPlace,
    GooglePlacesSource,
    has_apify_token,
    has_places_key,
    run_search,
    score_relevance_batch,
)
from core.config import settings as _settings_for_apify
from core.regions import WOJEWODZTWA, location_label, location_phrase
from agent.research import research_and_save
from core.config import settings
from core.db import (
    DraftStatus,
    EmailDraft,
    Event,
    Lead,
    LeadSegment,
    LeadStatus,
    SessionLocal,
    init_db,
)
from core.kill_switch import is_stopped, resume, stop
from core.llm import (
    ANTHROPIC_MODELS,
    GEMINI_MODELS,
    MODEL_PRICING,
    has_anthropic_key,
    has_gemini_key,
)

SEGMENT_VALUES: list[str] = [s.value for s in LeadSegment]


def _render_llm_selector() -> tuple[str, str]:
    """Sidebar: pick provider + model. Returns (provider, model)."""
    with st.sidebar:
        st.header("Model AI")

        provider = st.selectbox(
            "Provider",
            ["anthropic", "gemini"],
            index=0 if settings.llm_provider == "anthropic" else 1,
            key="llm_provider_select",
        )

        if provider == "anthropic":
            default_idx = (
                ANTHROPIC_MODELS.index(settings.anthropic_model)
                if settings.anthropic_model in ANTHROPIC_MODELS
                else 0
            )
            model = st.selectbox(
                "Model Anthropic",
                ANTHROPIC_MODELS,
                index=default_idx,
                key="llm_model_anthropic_select",
            )
            if has_anthropic_key():
                st.success("Klucz ANTHROPIC_API_KEY: OK")
            else:
                st.error(
                    "Brak ANTHROPIC_API_KEY. Dodaj w `.env` lokalnie albo w "
                    "Streamlit Cloud → Settings → Secrets."
                )
        else:
            default_idx = (
                GEMINI_MODELS.index(settings.gemini_model)
                if settings.gemini_model in GEMINI_MODELS
                else 0
            )
            model = st.selectbox(
                "Model Gemini",
                GEMINI_MODELS,
                index=default_idx,
                key="llm_model_gemini_select",
            )
            if has_gemini_key():
                st.success("Klucz GEMINI_API_KEY: OK")
            else:
                st.error(
                    "Brak GEMINI_API_KEY. Dodaj w `.env` lokalnie albo w "
                    "Streamlit Cloud → Settings → Secrets."
                )

        pricing = MODEL_PRICING.get((provider, model))
        if pricing:
            # Rough estimate: 10k input, 600 output per lead. Cache reads
            # cost less on Anthropic, ignored here.
            est = (10_000 * pricing["input"] + 600 * pricing["output"]) / 1_000_000
            st.caption(
                f"Szacunek per lead: ~${est:.4f}\n\n"
                f"100 leadów: ~${est * 100:.2f}"
            )
        else:
            st.caption("Pricing dla tego modelu nieznany — sprawdź w panelu providera.")

        return provider, model

st.set_page_config(page_title="Artmaker — Agent Handlowiec", layout="wide")

init_db()


def _start_of_day_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def render_dashboard() -> None:
    with SessionLocal() as session:
        total_leads = session.scalar(select(func.count(Lead.id))) or 0
        drafts_pending = (
            session.scalar(
                select(func.count(EmailDraft.id)).where(
                    EmailDraft.status == DraftStatus.DRAFT.value
                )
            )
            or 0
        )
        sent_today = (
            session.scalar(
                select(func.count(EmailDraft.id)).where(
                    EmailDraft.status == DraftStatus.SENT.value,
                    EmailDraft.sent_at >= _start_of_day_utc(),
                )
            )
            or 0
        )
        replied = (
            session.scalar(
                select(func.count(Lead.id)).where(Lead.status == LeadStatus.REPLIED.value)
            )
            or 0
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Leady (total)", total_leads)
    c2.metric("Drafty do review", drafts_pending)
    c3.metric("Wysłane dziś", sent_today)
    c4.metric("Odpowiedzi", replied)

    st.divider()
    st.subheader("Status agenta")

    stopped = is_stopped()
    bcol1, bcol2 = st.columns([1, 4])
    with bcol1:
        if stopped:
            if st.button("Wznów agenta", type="primary", use_container_width=True):
                resume()
                st.rerun()
        else:
            if st.button("ZATRZYMAJ AGENTA", type="primary", use_container_width=True):
                stop("stopped from GUI")
                st.rerun()
    with bcol2:
        if stopped:
            st.error("Agent ZATRZYMANY (STOP.txt obecny). Skrypty agenta nie wykonują akcji.")
        else:
            st.success("Agent aktywny. Skrypty mogą wykonywać akcje.")
        if settings.dry_run:
            st.info("DRY_RUN=true — żadne zewnętrzne wywołania nie wyjdą (Woodpecker itp.).")

    st.divider()
    st.subheader("Ostatnie zdarzenia")
    with SessionLocal() as session:
        events = (
            session.execute(select(Event).order_by(Event.created_at.desc()).limit(10))
            .scalars()
            .all()
        )
    if not events:
        st.caption("Brak zdarzeń. Uruchom moduł agenta, żeby zobaczyć aktywność.")
        return
    df = pd.DataFrame(
        [
            {
                "kiedy": e.created_at.strftime("%Y-%m-%d %H:%M"),
                "poziom": e.level,
                "źródło": e.source or "",
                "typ": e.type,
                "wiadomość": e.message,
            }
            for e in events
        ]
    )
    st.dataframe(df, hide_index=True, use_container_width=True)


def _render_manual_entry_form(provider: str, model: str) -> None:
    with st.expander("Dodaj leada (researchuj URL)", expanded=False):
        st.caption(f"Researchuję modelem **{provider} / {model}** (zmień w panelu po lewej).")
        with st.form("manual_lead_form", clear_on_submit=True):
            url = st.text_input(
                "URL strony firmy",
                placeholder="https://przyklad.pl",
                help="Wklej link do strony www potencjalnego klienta. Agent ją przeczyta i oceni.",
            )
            c1, c2 = st.columns(2)
            segment_hint = c1.selectbox(
                "Segment (hint, opcjonalnie)",
                ["(pozwól agentowi wybrać)", *SEGMENT_VALUES],
                index=0,
            )
            city_hint = c2.text_input("Miasto (hint, opcjonalnie)", placeholder="np. Warszawa")
            force_refresh = st.checkbox(
                "🔄 Force refresh (re-researchuj jeśli URL już jest w bazie)",
                value=False,
            )
            submitted = st.form_submit_button("Researchuj", type="primary")

        if submitted:
            if not url.strip():
                st.warning("Podaj URL.")
                return
            seg = None if segment_hint == "(pozwól agentowi wybrać)" else segment_hint
            with st.status("Researchuję leada...", expanded=True) as status:
                try:
                    status.write("Sprawdzam czy lead nie istnieje w bazie...")
                    status.write("Pobieram treść strony i podstrony (kontakt, o nas, oferta)...")
                    status.write(f"Wysyłam do {provider}/{model} do oceny według rubryki...")
                    lead_id, result, was_researched = research_and_save(
                        url.strip(),
                        segment_hint=seg,
                        city_hint=city_hint.strip() or None,
                        provider=provider,
                        model=model,
                        force_refresh=force_refresh,
                    )
                    if not was_researched:
                        status.update(
                            label=f"Pominięte — lead #{lead_id} już istnieje", state="complete"
                        )
                        st.info(
                            f"Ten URL już jest w bazie jako lead #{lead_id}. "
                            "Zaznacz '🔄 Force refresh' żeby zresearchować ponownie."
                        )
                    else:
                        status.update(label=f"Gotowe — score {result.score.total}/10", state="complete")
                        st.success(
                            f"**{result.company_name}** zapisany jako lead #{lead_id}. "
                            f"Segment: `{result.segment}`, score: **{result.score.total}/10**."
                        )
                        st.caption(result.rationale)
                except Exception as exc:
                    status.update(label="Research nie powiódł się", state="error")
                    st.error(f"Błąd: {exc}")


def _score_label(score: float | None) -> str:
    if score is None:
        return "—"
    if score >= 7:
        return "HOT"
    if score >= 5:
        return "WARM"
    return "COLD"


SOURCE_LABELS = {
    "apify": "Apify Google Maps",
    "google_places": "Google Places API",
    "apify_allegro": "Apify Allegro",
    "apify_linkedin": "Apify LinkedIn",
    "csv": "Import CSV",
}


def _build_sources(selected: list[str], csv_bytes: bytes | None) -> list:
    """Map UI selection to LeadSource instances."""
    sources: list = []
    if "apify" in selected:
        sources.append(ApifySource())
    if "google_places" in selected:
        sources.append(GooglePlacesSource())
    if "apify_allegro" in selected:
        sources.append(ApifyAllegroSource())
    if "apify_linkedin" in selected:
        sources.append(ApifyLinkedInSource())
    if "csv" in selected:
        sources.append(CSVSource(csv_bytes=csv_bytes))
    return sources


def render_discovery(provider: str, model: str) -> None:
    st.subheader("Pozyskiwanie leadów")
    st.caption(
        "Wybierz źródła, podaj zapytanie i uruchom kilku agentów równolegle. "
        "Wyniki są deduplikowane po adresie www, zaznaczasz które researchować."
    )

    apify_ok = has_apify_token()
    places_ok = has_places_key()
    allegro_ok = apify_ok and bool(_settings_for_apify.apify_allegro_actor)
    linkedin_ok = apify_ok and bool(_settings_for_apify.apify_linkedin_actor)

    row1 = st.columns(3)
    use_apify = row1[0].checkbox(
        f"Apify Google Maps {'✓' if apify_ok else '✗'}",
        value=apify_ok,
        disabled=not apify_ok,
        help="Apify Google Maps Scraper actor. Wymaga APIFY_API_TOKEN.",
    )
    use_places = row1[1].checkbox(
        f"Google Places API {'✓' if places_ok else '✗'}",
        value=places_ok,
        disabled=not places_ok,
        help="Google Places API (New) Text Search. Wymaga GOOGLE_PLACES_API_KEY.",
    )
    use_csv = row1[2].checkbox(
        "Import CSV",
        value=False,
        help="Wgraj CSV z kolumną 'url' (i opcjonalnie 'name', 'address', 'phone').",
    )
    row2 = st.columns(3)
    use_allegro = row2[0].checkbox(
        f"Apify Allegro {'✓' if allegro_ok else '✗'}",
        value=False,
        disabled=not allegro_ok,
        help=(
            "Apify Allegro Scraper. Wymaga APIFY_API_TOKEN + APIFY_ALLEGRO_ACTOR "
            "(actor id z apify.com/store)."
        ),
    )
    use_linkedin = row2[1].checkbox(
        f"Apify LinkedIn {'✓' if linkedin_ok else '✗'}",
        value=False,
        disabled=not linkedin_ok,
        help=(
            "Apify LinkedIn Companies Scraper. Wymaga APIFY_API_TOKEN + "
            "APIFY_LINKEDIN_ACTOR. Sprawdź TOS LinkedIn i przepisy GDPR."
        ),
    )

    csv_bytes: bytes | None = None
    if use_csv:
        uploaded = st.file_uploader("Plik CSV", type=["csv"], key="discovery_csv")
        if uploaded is not None:
            csv_bytes = uploaded.read()

    with st.form("discovery_form"):
        c1, c2 = st.columns([2, 1])
        segment = c1.selectbox("Segment", SEGMENT_VALUES, key="discovery_segment")
        per_source = c2.number_input(
            "Max / źródło", min_value=5, max_value=50, value=20, key="discovery_limit"
        )

        loc_mode = st.radio(
            "Tryb lokalizacji",
            ["Miasto", "Województwo", "Cała Polska"],
            horizontal=True,
            key="discovery_loc_mode",
            help=(
                "Miasto = wąsko (np. Łask). "
                "Województwo = szeroko (cały region, np. mazowieckie). "
                "Cała Polska = bez ograniczeń."
            ),
        )
        loc_col1, loc_col2 = st.columns(2)
        if loc_mode == "Miasto":
            city = loc_col1.text_input(
                "Miasto", placeholder="Warszawa", key="discovery_city"
            )
            wojewodztwo = ""
        elif loc_mode == "Województwo":
            wojewodztwo = loc_col1.selectbox(
                "Województwo", WOJEWODZTWA, key="discovery_wojewodztwo"
            )
            city = ""
        else:
            loc_col1.caption("Szukam w całej Polsce. Może zwrócić więcej niż 20 wyników na źródło — zwiększ limit.")
            city = ""
            wojewodztwo = ""

        custom_target = st.text_area(
            "Lub opisz własny target (free-form, ma pierwszeństwo nad segmentem)",
            placeholder=(
                "Np. 'producenci sztalug i ram do obrazów w Polsce, którzy mogliby "
                "kupować od nas hurtowo lub robić private label'"
            ),
            height=70,
            key="discovery_custom_target",
        )
        f1, f2 = st.columns([3, 2])
        use_relevance_filter = f1.checkbox(
            "Filtr trafności LLM (zalecane — odsiewa mismatche zanim wydasz tokeny na research)",
            value=True,
            key="discovery_use_filter",
        )
        relevance_threshold = f2.slider(
            "Próg trafności (auto-zaznacz ≥)",
            min_value=0, max_value=10, value=6, key="discovery_threshold",
            help="Wpisy poniżej progu nie są domyślnie zaznaczone (możesz je dozaznaczyć ręcznie).",
        )
        auto_research = st.checkbox(
            "🔥 Auto-research: po wyszukaniu odpal research na wszystkich pasujących bez ręcznego klikania",
            value=False,
            key="discovery_auto_research",
            help="Łączy Szukaj → Filtr → Bulk research w jeden ruch. Wymaga włączonego filtra trafności.",
        )
        ap1, ap2 = st.columns([3, 2])
        auto_draft = ap1.checkbox(
            "✉️ Auto-pipeline: gdy research wyjdzie z wysokim score, od razu generuj draft maila",
            value=False,
            key="discovery_auto_draft",
            help=(
                "Po pozytywnym researchu odpala generator maila (agent/generate.py) "
                "i zapisuje draft do review w zakładce Drafty."
            ),
        )
        auto_draft_threshold = ap2.slider(
            "Próg score → draft",
            min_value=0, max_value=10, value=7,
            key="discovery_auto_draft_threshold",
        )
        submitted = st.form_submit_button("Szukaj", type="primary")

    if submitted:
        selected_sources = [
            name
            for name, on in (
                ("apify", use_apify),
                ("google_places", use_places),
                ("apify_allegro", use_allegro),
                ("apify_linkedin", use_linkedin),
                ("csv", use_csv),
            )
            if on
        ]
        if not selected_sources:
            st.warning("Zaznacz przynajmniej jedno źródło.")
            return
        if "csv" in selected_sources and csv_bytes is None:
            st.warning("Wybrałeś CSV, ale nie wgrałeś pliku.")
            return

        loc_suffix = location_phrase(loc_mode, city=city, wojewodztwo=wojewodztwo)
        if any(s != "csv" for s in selected_sources) and loc_mode == "Miasto" and not city.strip():
            st.warning("Tryb 'Miasto' wymaga nazwy miasta. Wybierz inny tryb albo wpisz miasto.")
            return
        if any(s != "csv" for s in selected_sources) and loc_mode == "Województwo" and not wojewodztwo:
            st.warning("Tryb 'Województwo' wymaga wybrania województwa.")
            return

        custom_target_clean = custom_target.strip()
        # Search query: free-form description if provided, else preset segment
        # value with underscores replaced by spaces for nicer Google parsing.
        search_phrase = (
            custom_target_clean
            if custom_target_clean
            else segment.replace("_", " ")
        )
        query = f"{search_phrase} {loc_suffix}".strip()

        sources = _build_sources(selected_sources, csv_bytes)
        with st.spinner(f"Szukam '{query}' w {len(sources)} źródłach równolegle..."):
            places, diagnostics = run_search(
                sources, query=query, max_results_per_source=int(per_source)
            )

        relevance_map: dict[int, dict] = {}
        relevance_warning: str | None = None
        if use_relevance_filter and places:
            with st.spinner(
                f"Filtr trafności: oceniam {len(places)} kandydatów tanim modelem..."
            ):
                try:
                    items, _usage = score_relevance_batch(
                        places,
                        segment=segment,
                        city=location_label(loc_mode, city=city, wojewodztwo=wojewodztwo),
                        custom_description=custom_target_clean or None,
                    )
                    for item in items:
                        if 0 <= item.idx < len(places):
                            relevance_map[item.idx] = {
                                "score": int(item.score),
                                "reason": item.reason,
                            }
                except Exception as exc:
                    relevance_warning = (
                        f"Filtr trafności padł ({exc}). Pokazuję wszystkich kandydatów bez scoringu."
                    )

        st.session_state["discovery_places"] = [p.model_dump() for p in places]
        st.session_state["discovery_query"] = query
        st.session_state["discovery_diag"] = [d.model_dump() for d in diagnostics]
        st.session_state["discovery_segment_used"] = segment
        st.session_state["discovery_custom_target_used"] = custom_target_clean
        # Pass a meaningful location hint to research_and_save: the city if
        # provided, else None (research won't override LLM's own extraction).
        st.session_state["discovery_city_used"] = (
            city.strip() if loc_mode == "Miasto" else ""
        )
        st.session_state["discovery_relevance"] = relevance_map
        st.session_state["discovery_relevance_warning"] = relevance_warning
        st.session_state["discovery_threshold_used"] = int(relevance_threshold)
        st.session_state["discovery_auto_research_pending"] = bool(
            auto_research and use_relevance_filter and relevance_map
        )
        st.session_state["discovery_auto_draft_threshold"] = (
            int(auto_draft_threshold) if auto_draft else None
        )

    places_data = st.session_state.get("discovery_places") or []
    diag_data = st.session_state.get("discovery_diag") or []

    if diag_data:
        diag_cols = st.columns(len(diag_data))
        for idx, d in enumerate(diag_data):
            label = SOURCE_LABELS.get(d["source"], d["source"])
            if d.get("error"):
                diag_cols[idx].error(f"{label}: {d['error'][:80]}")
            else:
                diag_cols[idx].success(
                    f"{label}: {len(d.get('places', []))} firm "
                    f"({d.get('duration_s', 0)}s)"
                )

    if not places_data:
        return

    relevance_map: dict[int, dict] = st.session_state.get("discovery_relevance", {}) or {}
    relevance_warning = st.session_state.get("discovery_relevance_warning")
    threshold = int(st.session_state.get("discovery_threshold_used", 6))

    st.markdown(f"### {len(places_data)} firm znalezionych dla `{st.session_state.get('discovery_query', '')}`")
    if relevance_warning:
        st.warning(relevance_warning)

    if relevance_map:
        kept = sum(1 for s in relevance_map.values() if s["score"] >= threshold)
        rejected = len(relevance_map) - kept
        st.caption(
            f"Filtr trafności: {kept} pasuje (≥{threshold}), {rejected} odrzucone. "
            "Sortuję od najtrafniejszych. Możesz przesunąć zaznaczenia ręcznie."
        )

    # Build rows; if scoring is on, sort by relevance desc so the best leads
    # surface first.
    indexed_places = list(enumerate(places_data))
    if relevance_map:
        def _key(item: tuple[int, dict]) -> tuple[int, int]:
            i, p = item
            score = relevance_map.get(i, {}).get("score", -1)
            reviews = p.get("review_count") or 0
            return (-score, -reviews)
        indexed_places.sort(key=_key)

    df_rows = []
    for original_idx, p in indexed_places:
        rel = relevance_map.get(original_idx)
        score_val = rel["score"] if rel else None
        # Default selection: only "good enough" leads with a website.
        if rel:
            default_selected = bool(p.get("website")) and score_val >= threshold
        else:
            default_selected = bool(p.get("website"))
        df_rows.append(
            {
                "_orig_idx": original_idx,
                "Wybierz": default_selected,
                "Trafność": score_val if score_val is not None else "—",
                "Komentarz": (rel["reason"] if rel else ""),
                "Źródło": SOURCE_LABELS.get(p["source"], p["source"]),
                "Nazwa": p["name"],
                "Adres": p.get("address") or "—",
                "Ocena": p.get("rating") or "—",
                "Opinii": p.get("review_count") or "—",
                "WWW": p.get("website") or "(brak)",
            }
        )
    df = pd.DataFrame(df_rows)
    visible_cols = [c for c in df.columns if c != "_orig_idx"]
    edited = st.data_editor(
        df[visible_cols],
        column_config={
            "Wybierz": st.column_config.CheckboxColumn(
                help="Tylko firmy z adresem www zostaną zresearchowane."
            ),
            "Trafność": st.column_config.NumberColumn(
                help="Ocena LLM 0-10 (10 = idealny lead). '—' = filtr wyłączony.",
                format="%d",
            ),
            "Komentarz": st.column_config.TextColumn(width="medium"),
            "WWW": st.column_config.LinkColumn(),
        },
        hide_index=True,
        use_container_width=True,
        disabled=[c for c in visible_cols if c != "Wybierz"],
        key="discovery_table",
    )
    # Map editor row indexes (positions in sorted df) back to original places_data indexes.
    selected_orig_idxs = [
        int(df.iloc[row_pos]["_orig_idx"])
        for row_pos in edited.index[edited["Wybierz"]].tolist()
    ]
    selected_places = [
        places_data[i] for i in selected_orig_idxs if places_data[i].get("website")
    ]
    skipped_no_website = sum(
        1 for i in selected_orig_idxs if not places_data[i].get("website")
    )
    if skipped_no_website:
        st.caption(f"Pominę {skipped_no_website} zaznaczonych firm bez adresu www.")

    # Auto-research path: if user ticked the checkbox before searching, fire
    # research on every place above threshold without requiring another click.
    auto_pending = st.session_state.pop("discovery_auto_research_pending", False)
    auto_draft_threshold_pending = st.session_state.pop(
        "discovery_auto_draft_threshold", None
    )
    if auto_pending:
        auto_targets = [
            places_data[i]
            for i, rel in relevance_map.items()
            if rel["score"] >= threshold and places_data[i].get("website")
        ]
        if auto_targets:
            draft_msg = (
                f", auto-draft dla score ≥ {auto_draft_threshold_pending}"
                if auto_draft_threshold_pending is not None else ""
            )
            st.info(
                f"🔥 Auto-research: lecę na {len(auto_targets)} pasujących leadach "
                f"(trafność ≥ {threshold}){draft_msg}."
            )
            _run_bulk_research(
                auto_targets, provider, model,
                auto_draft_threshold=auto_draft_threshold_pending,
            )
        else:
            st.warning("Auto-research: żaden kandydat nie przeszedł progu trafności.")

    if st.button(
        f"Researchuj zaznaczone ({len(selected_places)}) — model: {provider}/{model}",
        type="primary",
        disabled=not selected_places,
    ):
        _run_bulk_research(selected_places, provider, model)


def _run_bulk_research(
    targets: list[dict],
    provider: str,
    model: str,
    *,
    auto_draft_threshold: int | None = None,
) -> None:
    """Loop selected places through research_and_save with progress + log.

    Skips URLs that already exist in the leads table (dedup via Lead.website).
    If `auto_draft_threshold` is set, leads with score >= threshold trigger
    immediate draft generation in the same run.
    """
    progress = st.progress(0.0, text="Startuję bulk research...")
    log_area = st.container()
    ok, fail, skipped = 0, 0, 0
    drafts_made, drafts_failed = 0, 0
    seg_hint = st.session_state.get("discovery_segment_used")
    city_hint = st.session_state.get("discovery_city_used") or None
    for i, place in enumerate(targets, start=1):
        url = place["website"]
        progress.progress(
            i / len(targets),
            text=f"{i}/{len(targets)}: {place['name']}",
        )
        try:
            lead_id, result, was_researched = research_and_save(
                url,
                segment_hint=seg_hint,
                city_hint=city_hint,
                provider=provider,
                model=model,
            )
            if not was_researched:
                skipped += 1
                log_area.info(
                    f"⏭️ {place['name']} — duplikat (lead #{lead_id} już w bazie), pomijam."
                )
                continue
            ok += 1
            log_area.success(
                f"#{lead_id} **{result.company_name}** — score {result.score.total}/10"
            )
            if auto_draft_threshold is not None and result.score.total >= auto_draft_threshold:
                try:
                    from agent.generate import generate_draft_for_lead

                    draft_id = generate_draft_for_lead(
                        lead_id, provider=provider, model=model
                    )
                    drafts_made += 1
                    log_area.success(
                        f"✉️ Draft #{draft_id} wygenerowany dla leada #{lead_id} "
                        f"(score {result.score.total} ≥ próg {auto_draft_threshold})"
                    )
                except Exception as draft_exc:
                    drafts_failed += 1
                    log_area.warning(
                        f"⚠️ Draft dla leada #{lead_id} się nie udał: {draft_exc}"
                    )
        except Exception as exc:
            fail += 1
            log_area.error(f"❌ {place['name']} ({url}): {exc}")
    progress.progress(
        1.0,
        text=f"Gotowe — {ok} OK, {skipped} duplikatów, {fail} błędów.",
    )
    summary = f"Bulk research: {ok} researche, {skipped} pominięte (duplikaty), {fail} błędów."
    if auto_draft_threshold is not None:
        summary += f" Drafty: {drafts_made} OK, {drafts_failed} fail."
    st.success(summary)


def render_leads(provider: str, model: str) -> None:
    _render_manual_entry_form(provider, model)

    with SessionLocal() as session:
        leads = (
            session.execute(select(Lead).order_by(Lead.score.desc().nullslast(), Lead.created_at.desc()))
            .scalars()
            .all()
        )

    if not leads:
        st.info("Baza leadów jest pusta. Użyj formularza powyżej, żeby dodać pierwszego.")
        return

    f1, f2, f3 = st.columns([2, 2, 2])
    seg_filter = f1.multiselect("Segment", SEGMENT_VALUES, default=[])
    status_filter = f2.multiselect(
        "Status", [s.value for s in LeadStatus], default=[]
    )
    min_score = f3.slider("Min score", 0.0, 10.0, 0.0, 0.5)

    filtered = [
        lead
        for lead in leads
        if (not seg_filter or lead.segment in seg_filter)
        and (not status_filter or lead.status in status_filter)
        and (lead.score is None or lead.score >= min_score)
    ]

    st.caption(f"Pokazuję {len(filtered)} z {len(leads)} leadów.")

    df = pd.DataFrame(
        [
            {
                "id": lead.id,
                "score": f"{_score_label(lead.score)} {lead.score:.1f}" if lead.score is not None else "-",
                "firma": lead.company_name,
                "segment": lead.segment,
                "miasto": lead.city or "-",
                "email": lead.email or "-",
                "kontakt": lead.contact_name or "-",
                "status": lead.status,
                "dodany": lead.created_at.strftime("%Y-%m-%d"),
            }
            for lead in filtered
        ]
    )
    st.dataframe(df, hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("Szczegóły leadów")

    for lead in filtered[:20]:
        score_display = f"{lead.score:.1f}" if lead.score is not None else "-"
        title = (
            f"#{lead.id}  {_score_label(lead.score)} {score_display}/10  "
            f"— {lead.company_name}  ({lead.segment})"
        )
        with st.expander(title):
            data = lead.research_data or {}
            score = data.get("score") or {}

            c1, c2 = st.columns([2, 1])
            with c1:
                if data.get("rationale"):
                    st.markdown(f"**Uzasadnienie:** {data['rationale']}")

                hooks = data.get("concrete_hooks") or []
                if hooks:
                    st.markdown("**Konkretne sygnały (hooki do personalizacji):**")
                    for h in hooks:
                        st.markdown(f"- *{h.get('text', '')}* — _{h.get('source', '')}_")

                warnings = data.get("warning_flags") or []
                if warnings:
                    st.warning("Warning flags: " + "; ".join(warnings))

            with c2:
                st.markdown("**Score breakdown:**")
                if score:
                    st.markdown(
                        f"- Activity: {score.get('activity', '?')}/2\n"
                        f"- Scale: {score.get('scale', '?')}/2\n"
                        f"- Fit: {score.get('fit', '?')}/2\n"
                        f"- Bulk potential: {score.get('bulk_potential', '?')}/2\n"
                        f"- Contact quality: {score.get('contact_quality', '?')}/2\n"
                        f"- **TOTAL: {score.get('total', '?')}/10**"
                    )
                if data.get("estimated_monthly_volume"):
                    st.markdown(f"**Szacowany wolumen:** {data['estimated_monthly_volume']}")

                st.markdown("**Kontakt:**")
                st.markdown(
                    f"- Email: {lead.email or '-'}\n"
                    f"- Telefon: {lead.phone or '-'}\n"
                    f"- WWW: {lead.website or '-'}\n"
                    f"- Instagram: {lead.instagram or '-'}\n"
                    f"- Osoba: {lead.contact_name or '-'}"
                )

            draft_col, del_col, _ = st.columns([2, 1, 4])
            can_draft = lead.status in (
                LeadStatus.RESEARCHED.value, LeadStatus.DRAFTED.value
            )
            if draft_col.button(
                "✉️ Generuj draft maila",
                key=f"gen-draft-{lead.id}",
                disabled=not can_draft,
            ):
                from agent.generate import generate_draft_for_lead
                try:
                    with st.spinner(f"Generuję draft dla #{lead.id}..."):
                        draft_id = generate_draft_for_lead(
                            lead.id, provider=provider, model=model
                        )
                    st.success(f"Draft #{draft_id} zapisany. Sprawdź zakładkę Drafty.")
                except Exception as exc:
                    st.error(f"Generator padł: {exc}")
            if del_col.button("Usuń leada", key=f"delete-lead-{lead.id}"):
                with SessionLocal() as s:
                    obj = s.get(Lead, lead.id)
                    if obj is not None:
                        s.delete(obj)
                        s.commit()
                st.rerun()

    if len(filtered) > 20:
        st.caption(f"...i {len(filtered) - 20} więcej (zawęź filtrami).")


def render_drafts(provider: str, model: str) -> None:
    from agent.generate import generate_all_researched

    with st.expander("⚙️ Bulk-generuj drafty z researchowanych leadów", expanded=False):
        with SessionLocal() as session:
            researched_count = (
                session.execute(
                    select(func.count(Lead.id)).where(
                        Lead.status == LeadStatus.RESEARCHED.value
                    )
                ).scalar()
                or 0
            )
        bg1, bg2 = st.columns([3, 1])
        min_score = bg2.slider(
            "Min score", min_value=0, max_value=10, value=6, key="bulk_drafts_min"
        )
        if bg1.button(
            f"Wygeneruj drafty ({researched_count} researchowanych w bazie) — {provider}/{model}",
            disabled=researched_count == 0,
            type="primary",
        ):
            with st.spinner("Generuję drafty po kolei..."):
                made, failed = generate_all_researched(
                    provider=provider, model=model, min_score=float(min_score),
                )
            st.success(f"Gotowe — {made} draftów wygenerowanych, {failed} błędów.")
            st.rerun()

    with SessionLocal() as session:
        drafts = (
            session.execute(
                select(EmailDraft)
                .where(EmailDraft.status == DraftStatus.DRAFT.value)
                .order_by(EmailDraft.created_at.desc())
            )
            .scalars()
            .all()
        )
        # Eagerly resolve lead names to avoid lazy-loading after session close.
        rows = [(d.id, d.lead.company_name, d.subject, d.full_preview) for d in drafts]

    if not rows:
        st.info("Brak draftów do review. Wygeneruj nowe powyżej, lub odpal `agent/generate.py`.")
        return

    for draft_id, company, subject, preview in rows:
        with st.expander(f"#{draft_id} — {company} | {subject or '(brak tematu)'}"):
            st.text(preview or "(brak treści)")
            c1, c2, c3 = st.columns(3)
            if c1.button("Zatwierdź", key=f"approve-{draft_id}"):
                with SessionLocal() as session:
                    obj = session.get(EmailDraft, draft_id)
                    obj.status = DraftStatus.APPROVED.value
                    session.commit()
                st.rerun()
            if c2.button("Odrzuć", key=f"reject-{draft_id}"):
                with SessionLocal() as session:
                    obj = session.get(EmailDraft, draft_id)
                    obj.status = DraftStatus.REJECTED.value
                    session.commit()
                st.rerun()
            c3.button("Edytuj (TODO)", key=f"edit-{draft_id}", disabled=True)


def render_logs() -> None:
    levels = st.multiselect(
        "Poziom",
        ["DEBUG", "INFO", "WARNING", "ERROR"],
        default=["INFO", "WARNING", "ERROR"],
    )
    limit = st.slider("Liczba wpisów", 10, 500, 100)

    with SessionLocal() as session:
        q = select(Event).order_by(Event.created_at.desc()).limit(limit)
        if levels:
            q = q.where(Event.level.in_(levels))
        events = session.execute(q).scalars().all()

    if not events:
        st.caption("Brak logów spełniających kryteria.")
        return

    df = pd.DataFrame(
        [
            {
                "kiedy": e.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "poziom": e.level,
                "źródło": e.source or "",
                "typ": e.type,
                "wiadomość": e.message,
            }
            for e in events
        ]
    )
    st.dataframe(df, hide_index=True, use_container_width=True)


selected_provider, selected_model = _render_llm_selector()

st.title("Artmaker — Agent Handlowiec")
st.caption(
    f"Firma: {settings.company_name} • "
    f"Właściciel: {settings.owner_name or '(uzupełnij OWNER_NAME w .env)'}"
)

tab_dashboard, tab_discovery, tab_leads, tab_drafts, tab_logs = st.tabs(
    ["Dashboard", "Pozyskiwanie", "Leady", "Drafty", "Logi"]
)

with tab_dashboard:
    render_dashboard()

with tab_discovery:
    render_discovery(selected_provider, selected_model)

with tab_leads:
    render_leads(selected_provider, selected_model)

with tab_drafts:
    render_drafts(selected_provider, selected_model)

with tab_logs:
    render_logs()
