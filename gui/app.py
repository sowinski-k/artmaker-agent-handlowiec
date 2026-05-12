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
from gui.components import (
    activity_feed,
    badge,
    card_close,
    card_head,
    data_table,
    funnel,
    page_head,
    sb_foot,
    sb_item,
    sb_logo,
    sb_section,
    stat,
    system_status,
    time_range_html,
    topbar,
)
from gui.landing import render_landing
from gui.theme import APP_NAME, inject_global_css

SEGMENT_VALUES: list[str] = [s.value for s in LeadSegment]


def _render_sidebar_nav() -> None:
    """Render branded sidebar w stylu ecombinat-dashboard.html: logo + grouped nav.

    Nawigacja jest dekoracyjna (HTML divs) - na razie tylko wskazuje
    strukturę. Faktyczna kontrola modułu jest przez tabs w content area.
    """
    with st.sidebar:
        sb_logo()

        # HALA - core navigation
        sb_section("Hala")
        sb_item("Pulpit", icon="layout-dashboard", active=True)
        sb_item("Projekty", icon="folder", disabled=True)
        sb_item("Biblioteka", icon="photo", disabled=True)

        # KUŹNIA - moduły
        sb_section("Kuźnia")
        sb_item("Agenci AI", icon="robot", count=1, active=True)
        sb_item("Zdjęcia produktowe", icon="camera", disabled=True)
        sb_item("Wideo", icon="video", disabled=True)
        sb_item("Opisy AI", icon="wand", disabled=True)
        sb_item("Usuń tło", icon="eraser", disabled=True)

        # INTEGRACJE
        sb_section("Integracje")
        sb_item("Woodpecker", icon="api")
        sb_item("Apify", icon="package")
        sb_item("Google Places", icon="map-pin")


def _render_llm_selector() -> tuple[str, str]:
    """Sidebar: pick provider + model. Returns (provider, model)."""
    with st.sidebar:
        sb_section("Model AI")

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

st.set_page_config(
    page_title=f"{APP_NAME} — Agenci AI",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_global_css()


# ─── Auth flow: landing page → password gate → dashboard ───
if not render_landing(password_required=True):
    st.stop()

init_db()


def _start_of_day_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def render_dashboard() -> None:
    """Pulpit Ecombinat — pełny widok w stylu ecombinat-dashboard.html."""
    # ─── Stats ───────────────────────────────────────────────────────────
    with SessionLocal() as session:
        total_leads = session.scalar(select(func.count(Lead.id))) or 0
        researched = session.scalar(
            select(func.count(Lead.id)).where(Lead.status == LeadStatus.RESEARCHED.value)
        ) or 0
        drafted = session.scalar(
            select(func.count(Lead.id)).where(Lead.status == LeadStatus.DRAFTED.value)
        ) or 0
        drafts_pending = session.scalar(
            select(func.count(EmailDraft.id)).where(EmailDraft.status == DraftStatus.DRAFT.value)
        ) or 0
        sent_today = session.scalar(
            select(func.count(EmailDraft.id)).where(
                EmailDraft.status == DraftStatus.SENT.value,
                EmailDraft.sent_at >= _start_of_day_utc(),
            )
        ) or 0
        sent_total = session.scalar(
            select(func.count(EmailDraft.id)).where(EmailDraft.status == DraftStatus.SENT.value)
        ) or 0
        replied = session.scalar(
            select(func.count(Lead.id)).where(Lead.status == LeadStatus.REPLIED.value)
        ) or 0
        bounced = session.scalar(
            select(func.count(Lead.id)).where(Lead.status == LeadStatus.BOUNCED.value)
        ) or 0
        avg_score = session.scalar(select(func.avg(Lead.score))) or 0.0
        hot_leads = session.scalar(
            select(func.count(Lead.id)).where(Lead.score >= 7.0)
        ) or 0

    reply_rate_str = f"{(replied / max(sent_total, 1)) * 100:.1f}" if sent_total > 0 else "—"
    avg_score_str = f"{avg_score:.1f}" if avg_score else "—"

    # Sparkline mock data (TODO: prawdziwe trendy z DB po dat)
    spark_up = [3, 5, 4, 6, 8, 9, 12, 14, 18, 22, 28, hot_leads or 30]
    spark_flat = [10, 11, 10, 12, 13, 12, 14, 14, 15, 16, 16, 17]
    spark_drafts = [0, 0, 2, 3, 5, 7, 8, 10, 12, 14, 14, drafts_pending or 16]

    # ROW 1
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(stat(
        "Leady w bazie", total_leads, icon="database",
        delta=f"{researched} researched" if researched else None,
        sparkline=spark_up, spark_color="#D4212C",
    ), unsafe_allow_html=True)
    c2.markdown(stat(
        "Hot leady", hot_leads, unit="≥ 7/10", icon="flame",
        delta=f"{hot_leads}/{total_leads} ogółem" if total_leads else "0 ogółem",
        delta_dir="up" if hot_leads > 0 else "flat",
        sparkline=spark_up, spark_color="#D4212C",
    ), unsafe_allow_html=True)
    c3.markdown(stat(
        "Drafty do review", drafts_pending, icon="mail-forward",
        delta=f"{drafted} oczekuje na draft" if drafted else None,
        sparkline=spark_drafts, spark_color="#1C1C1C",
    ), unsafe_allow_html=True)
    c4.markdown(stat(
        "Średni score", avg_score_str, unit="/ 10", icon="chart-bar",
        delta="vs poprzedni okres" if avg_score else None,
        sparkline=spark_flat, spark_color="#6B7280",
    ), unsafe_allow_html=True)

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # ROW 2
    c5, c6, c7, c8 = st.columns(4)
    c5.markdown(stat(
        "Researchowane", researched, icon="search",
        sparkline=spark_up, spark_color="#1C1C1C",
    ), unsafe_allow_html=True)
    c6.markdown(stat(
        "Wysłane dziś", sent_today, icon="send",
        delta=f"{sent_total} łącznie" if sent_total else None,
        sparkline=spark_drafts, spark_color="#D4212C",
    ), unsafe_allow_html=True)
    c7.markdown(stat(
        "Odpowiedzi", replied, icon="message-circle",
        delta=f"{bounced} bounce" if bounced else None,
        delta_dir="up" if replied > 0 else "flat",
        sparkline=spark_up, spark_color="#8F1018",
    ), unsafe_allow_html=True)
    c8.markdown(stat(
        "Reply rate", reply_rate_str, unit="%", icon="trending-up",
        delta="vs ostatnie 30d" if sent_total > 0 else None,
        delta_dir="up" if replied > 0 else "flat",
        sparkline=spark_flat, spark_color="#D4212C",
    ), unsafe_allow_html=True)

    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)

    # ─── ROW 3: Funnel pipeline + Activity feed ──────────────────────────
    fcol, acol = st.columns([1, 1])
    with fcol:
        st.markdown(
            card_head("Pipeline cold-mail", icon="funnel",
                      right_html='<span style="font-size:11.5px;">30 dni</span>'),
            unsafe_allow_html=True,
        )
        # Realne pipeline counts
        new_leads = total_leads
        researched_pct = (researched / new_leads * 100) if new_leads else 0
        drafted_pct = (drafted / new_leads * 100) if new_leads else 0
        sent_pct = (sent_total / new_leads * 100) if new_leads else 0
        replied_pct = (replied / new_leads * 100) if new_leads else 0
        funnel(
            [
                {"label": "Pozyskane", "value": new_leads, "percent": 100.0, "icon": "upload"},
                {"label": "Researched", "value": researched + drafted + sent_total + replied,
                 "percent": researched_pct + drafted_pct + sent_pct + replied_pct, "icon": "search"},
                {"label": "Z draftem", "value": drafted + sent_total + replied,
                 "percent": drafted_pct + sent_pct + replied_pct, "icon": "check"},
                {"label": "Wysłane", "value": sent_total + replied,
                 "percent": sent_pct + replied_pct, "icon": "send"},
                {"label": "Odpowiedzieli", "value": replied,
                 "percent": replied_pct, "icon": "message-circle"},
            ],
            accent_first=True,
            footer_label="Reply rate vs sent",
            footer_value=f"{reply_rate_str}%" if reply_rate_str != "—" else "—",
        )
        st.markdown(card_close(), unsafe_allow_html=True)

    with acol:
        st.markdown(
            card_head("Ostatnia aktywność", icon="activity",
                      right_html='<a href="#" style="font-size:11.5px;color:#6B7280;text-decoration:none;">Wszystkie →</a>'),
            unsafe_allow_html=True,
        )
        with SessionLocal() as session:
            events = session.execute(
                select(Event).order_by(Event.created_at.desc()).limit(8)
            ).scalars().all()

        if events:
            # Map Event level + source → ikona + accent
            def _icon_for(src: str, ev_type: str) -> tuple[str, bool]:
                src = (src or "").lower()
                ev_type = (ev_type or "").lower()
                if "research" in src: return ("search", True)
                if "discover" in src: return ("upload", True)
                if "generate" in src or "draft" in ev_type: return ("wand", True)
                if "push" in src or "send" in ev_type: return ("send", False)
                if "poll" in src: return ("refresh", False)
                if "error" in (src + ev_type): return ("x", False)
                return ("circle-dot", False)

            items = []
            now = datetime.now(timezone.utc)
            for e in events:
                ic, acc = _icon_for(e.source or "", e.type or "")
                # Bezpieczne escapowanie - DB messages mogą zawierać HTML
                safe_msg = (e.message or "")
                if len(safe_msg) > 90:
                    safe_msg = safe_msg[:87] + "..."
                # Escape HTML w wiadomościach
                import html as _h
                safe_msg = _h.escape(safe_msg)
                # Format time relative
                delta = now - e.created_at if e.created_at.tzinfo else now.replace(tzinfo=None) - e.created_at
                mins = int(delta.total_seconds() / 60)
                if mins < 1: time_str = "teraz"
                elif mins < 60: time_str = f"{mins}m"
                elif mins < 1440: time_str = f"{mins // 60}h"
                else: time_str = e.created_at.strftime("%m-%d")
                items.append({
                    "icon": ic, "accent": acc,
                    "text": f"<strong>{e.source or '—'}</strong> · {safe_msg}",
                    "time": time_str,
                })
            activity_feed(items)
        else:
            st.markdown(
                '<div style="padding:24px;color:#6B7280;font-size:13px;text-align:center;">'
                'Brak zdarzeń. Odpal pozyskiwanie żeby zobaczyć aktywność.'
                '</div>',
                unsafe_allow_html=True,
            )
        st.markdown(card_close(), unsafe_allow_html=True)

    # ─── ROW 4: Segment breakdown + System status + Skróty ──────────────
    s1, s2, s3 = st.columns(3)

    with s1:
        st.markdown(
            card_head("Leady wg segmentu", icon="layers-subtract"),
            unsafe_allow_html=True,
        )
        with SessionLocal() as session:
            seg_rows = session.execute(
                select(Lead.segment, func.count(Lead.id))
                .group_by(Lead.segment)
                .order_by(func.count(Lead.id).desc())
            ).all()
        if seg_rows:
            data_table(
                [{"label": "Segment"}, {"label": "Liczba", "num": True}],
                [[r[0] or "—", str(r[1])] for r in seg_rows],
            )
        else:
            st.markdown(
                '<div style="padding:24px;color:#6B7280;font-size:13px;text-align:center;">'
                'Brak leadów. Zacznij od Pozyskiwania.'
                '</div>',
                unsafe_allow_html=True,
            )
        st.markdown(card_close(), unsafe_allow_html=True)

    with s2:
        stopped = is_stopped()
        status_label = "stopped" if stopped else "operational"
        right_html = (
            f'<span style="font-family:JetBrains Mono,monospace;font-size:11px;">'
            f'<span class="status-dot {"err" if stopped else "ok"}"></span>{status_label}</span>'
        )
        st.markdown(
            card_head("Stan systemu", icon="server", right_html=right_html),
            unsafe_allow_html=True,
        )
        rows = [
            {"label": "Agent (STOP.txt)",
             "value": "stopped" if stopped else "running",
             "status": "err" if stopped else "ok"},
            {"label": "DRY_RUN",
             "value": "true · blokuje wysyłkę" if settings.dry_run else "false",
             "status": "warn" if settings.dry_run else "ok"},
            {"label": "Anthropic key",
             "value": "OK" if has_anthropic_key() else "brak",
             "status": "ok" if has_anthropic_key() else "warn"},
            {"label": "Gemini key",
             "value": "OK" if has_gemini_key() else "brak",
             "status": "ok" if has_gemini_key() else "warn"},
            {"label": "Apify token",
             "value": "OK" if has_apify_token() else "brak",
             "status": "ok" if has_apify_token() else "warn"},
            {"label": "Google Places",
             "value": "OK" if has_places_key() else "brak",
             "status": "ok" if has_places_key() else "warn"},
            {"label": "Dzienny limit researchu",
             "value": f"{int(_credits_used)}/{settings.daily_research_limit}",
             "status": "ok"},
        ]
        system_status(rows)
        st.markdown(card_close(), unsafe_allow_html=True)

    with s3:
        st.markdown(
            card_head("Co dalej", icon="bookmark",
                      right_html='<span style="font-size:11.5px;">sugestie</span>'),
            unsafe_allow_html=True,
        )
        suggestions = []
        if total_leads == 0:
            suggestions.append(("Zacznij Pozyskiwanie", "search"))
        if researched > 0 and drafts_pending == 0:
            suggestions.append((f"{researched} leadów czeka na drafty", "wand"))
        if drafts_pending > 0:
            suggestions.append((f"{drafts_pending} draftów do review", "mail-forward"))
        if not has_anthropic_key() and not has_gemini_key():
            suggestions.append(("Dodaj klucz API LLM", "key"))
        if settings.dry_run:
            suggestions.append(("Wyłącz DRY_RUN żeby wysyłać", "send"))
        if not suggestions:
            suggestions.append(("Wszystko ogarnięte", "check"))

        rows_html = "".join(
            f"""
            <div class="sys-row">
                <span class="sys-label" style="display:flex;align-items:center;gap:8px;">
                    <div class="tool-ico"><i class="ti ti-{ic}"></i></div>
                    {text}
                </span>
                <i class="ti ti-arrow-right" style="color:#9CA3AF;font-size:14px;"></i>
            </div>
            """
            for text, ic in suggestions
        )
        st.markdown(rows_html, unsafe_allow_html=True)
        st.markdown(card_close(), unsafe_allow_html=True)

    # ─── ROW 5: Agent kontrola (Stop/Start) ──────────────────────────────
    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
    stopped = is_stopped()
    cs1, cs2 = st.columns([1, 5])
    with cs1:
        if stopped:
            if st.button("▶️ Wznów agenta", type="primary", use_container_width=True):
                resume()
                st.rerun()
        else:
            if st.button("⏸ Zatrzymaj agenta", use_container_width=True):
                stop("stopped from GUI")
                st.rerun()
    with cs2:
        if stopped:
            st.error("Agent zatrzymany - STOP.txt obecny. Skrypty discovery/research/push się nie wykonują.")
        else:
            st.success("Agent aktywny - skrypty mogą wykonywać akcje.")


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
    st.subheader("🎯 Pozyskiwanie leadów")
    st.caption(
        f"Modele: research **{provider}/{model}**, draft też. "
        "Filtr trafności jedzie tanim Gemini flash-lite niezależnie."
    )

    apify_ok = has_apify_token()
    places_ok = has_places_key()
    allegro_ok = apify_ok and bool(_settings_for_apify.apify_allegro_actor)
    linkedin_ok = apify_ok and bool(_settings_for_apify.apify_linkedin_actor)

    with st.expander("📡 Źródła leadów", expanded=True):
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
            "✏️ Lub opisz własny target (free-form, nadpisuje segment powyżej)",
            placeholder=(
                "Np. 'producenci sztalug i ram do obrazów w Polsce, którzy mogliby "
                "kupować od nas hurtowo lub robić private label'"
            ),
            height=70,
            key="discovery_custom_target",
        )

        st.markdown("**⚡ Automatyzacja**")
        f1, f2 = st.columns([3, 1])
        use_relevance_filter = f1.checkbox(
            "🎯 Filtr trafności LLM",
            value=True,
            key="discovery_use_filter",
            help="Odsiewa mismatche taniutkim modelem zanim wydasz tokeny na research. ~$0.001 / 20 firm.",
        )
        relevance_threshold = f2.slider(
            "Min trafność",
            min_value=0, max_value=10, value=6, key="discovery_threshold",
        )

        a1, a2, a3 = st.columns([2, 2, 1])
        auto_research = a1.checkbox(
            "🔥 Auto-research",
            value=False,
            key="discovery_auto_research",
            help="Po filtrze odpala research na wszystkich pasujących bez klikania.",
        )
        auto_draft = a2.checkbox(
            "✉️ Auto-pipeline (draft)",
            value=False,
            key="discovery_auto_draft",
            help="Po researchu z wysokim score od razu generuje draft maila.",
        )
        auto_draft_threshold = a3.slider(
            "Min score draftu",
            min_value=0, max_value=10, value=7,
            key="discovery_auto_draft_threshold",
        )

        submitted = st.form_submit_button("🚀 Szukaj", type="primary", use_container_width=True)

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
        st.session_state["discovery_auto_draft_threshold_pending"] = (
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

    # Liczymy ile z places_data to duble (already_in_db)
    dups_count = sum(1 for p in places_data if p.get("existing_lead_id"))
    fresh_count = len(places_data) - dups_count

    title_query = st.session_state.get('discovery_query', '')
    st.markdown(f"### {len(places_data)} firm znalezionych dla `{title_query}`")
    if dups_count > 0:
        st.info(
            f"💾 **{dups_count} z {len(places_data)} firm jest już w Twojej bazie leadów**. "
            f"Filtr trafności pominął ich i nie wydał na nich tokenów. "
            f"Nowych do oceny: **{fresh_count}**."
        )

    show_duplicates = st.toggle(
        "Pokaż też duble z bazy",
        value=False,
        key="discovery_show_dups",
        help="Domyślnie chowamy firmy które już masz w bazie. Włącz żeby je zobaczyć.",
    )

    if relevance_warning:
        st.warning(relevance_warning)

    if relevance_map:
        # Tylko fresh leady liczą się do "kept/rejected" (duble nie idą do researchu)
        fresh_scores = [
            s for i, s in relevance_map.items()
            if not (i < len(places_data) and places_data[i].get("existing_lead_id"))
        ]
        kept = sum(1 for s in fresh_scores if s["score"] >= threshold)
        rejected = len(fresh_scores) - kept
        st.caption(
            f"Filtr trafności na świeżych leadach: {kept} pasuje (≥{threshold}), "
            f"{rejected} odrzucone. Sortuję od najtrafniejszych."
        )

    # Build rows; if scoring is on, sort by relevance desc so the best leads
    # surface first.
    indexed_places = list(enumerate(places_data))
    # Filtruj duble jeśli toggle wyłączony (domyślnie tak)
    if not show_duplicates:
        indexed_places = [(i, p) for i, p in indexed_places if not p.get("existing_lead_id")]

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
        in_db_lead_id = p.get("existing_lead_id")
        # Default selection: only "good enough" leads with a website AND not dup
        if in_db_lead_id is not None:
            default_selected = False  # nigdy nie zaznaczamy dubli (research je i tak skipnie)
        elif rel:
            default_selected = bool(p.get("website")) and score_val >= threshold
        else:
            default_selected = bool(p.get("website"))
        df_rows.append(
            {
                "_orig_idx": original_idx,
                "Wybierz": default_selected,
                "W bazie?": f"✓ #{in_db_lead_id}" if in_db_lead_id else "—",
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
        "discovery_auto_draft_threshold_pending", None
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


@st.cache_data(ttl=300)  # 5 min cache - Woodpecker rate-limity są twarde
def _cached_woodpecker_campaigns() -> list[tuple[int, str, str | None]]:
    """Cached list_campaigns. Returns (id, name, status) tuples żeby się
    serializowały dla @cache_data."""
    from agent.woodpecker import list_campaigns
    campaigns = list_campaigns()
    return [(c.id, c.name, c.status) for c in campaigns]


def render_drafts(provider: str, model: str) -> None:
    from agent.generate import generate_all_researched
    from agent.woodpecker import has_woodpecker_key

    # ---- Bulk generate sekcja ----
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

    # ---- Wysyłka: Woodpecker integracja ----
    wp_ok = has_woodpecker_key()
    if not wp_ok:
        st.info(
            "🔌 **Woodpecker nie skonfigurowany** — dodaj `WOODPECKER_API_KEY` "
            "w env / Railway Variables, żeby wysyłać drafty automatycznie. "
            "Bez tego możesz tylko zatwierdzać drafty (skopiujesz ręcznie)."
        )
        selected_campaign_id: int | None = None
    else:
        wp_col1, wp_col2 = st.columns([3, 1])
        # Kampanie - cached
        try:
            campaigns = _cached_woodpecker_campaigns()
        except Exception as exc:
            wp_col1.error(f"Nie udało się pobrać kampanii z Woodpeckera: {exc}")
            campaigns = []

        if not campaigns:
            wp_col1.warning(
                "Brak kampanii w Twoim Woodpeckerze. **Utwórz kampanię w UI Woodpeckera** "
                "(z sekwencją follow-upów i template'em maila zawierającym placeholdery "
                "`{{SNIPPET1}}..{{SNIPPET5}}` i `{{SNIPPET6}}` dla subject) i wróć tutaj."
            )
            selected_campaign_id = None
        else:
            campaign_options = {
                f"#{cid} — {name}" + (f" [{status}]" if status else ""): cid
                for cid, name, status in campaigns
            }
            selected_label = wp_col1.selectbox(
                "📤 Kampania docelowa",
                list(campaign_options.keys()),
                key="wp_campaign_select",
                help="Wybierz kampanię Woodpeckera do której będą trafiać zatwierdzone drafty.",
            )
            selected_campaign_id = campaign_options[selected_label]

        if wp_col2.button("🔄 Odśwież statusy", help="Pyta Woodpecker o aktualne statusy wysłanych leadów."):
            try:
                from scripts.poll_woodpecker import poll_statuses
                with st.spinner("Polling Woodpeckera..."):
                    counts = poll_statuses(max_leads=200)
                st.success(
                    f"Sprawdzone: {counts['checked']}, "
                    f"replied: {counts['replied']}, "
                    f"bounced: {counts['bounced']}, "
                    f"unchanged: {counts['unchanged']}, "
                    f"errors: {counts['errors']}"
                )
                _cached_woodpecker_campaigns.clear()
                st.rerun()
            except Exception as exc:
                st.error(f"Polling padł: {exc}")

        if settings.dry_run:
            st.warning(
                "⚠️ **DRY_RUN=true** w env. Wysyłka jest zablokowana - drafty nie wyjdą. "
                "Ustaw `DRY_RUN=false` w Railway Variables żeby aktywować wysyłkę."
            )

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
        # Eagerly load wszystkie pola przed close session
        rows = [
            {
                "id": d.id,
                "company": d.lead.company_name,
                "subject": d.subject,
                "preview": d.full_preview,
                "snippet1": d.snippet1,
                "snippet2": d.snippet2,
                "snippet3": d.snippet3,
                "snippet4": d.snippet4,
                "snippet5": d.snippet5,
                "edited_by_user": d.edited_by_user,
                "template_variant": d.template_variant,
            }
            for d in drafts
        ]

    if not rows:
        st.info("Brak draftów do review. Wygeneruj nowe powyżej, lub odpal `agent/generate.py`.")
        return

    for d in rows:
        draft_id = d["id"]
        edit_mode_key = f"edit_mode_{draft_id}"
        in_edit_mode = st.session_state.get(edit_mode_key, False)

        title_parts = [f"#{draft_id} — {d['company']} | {d['subject'] or '(brak tematu)'}"]
        if d["edited_by_user"]:
            title_parts.append("✏️ edytowany")
        if d["template_variant"]:
            track = d["template_variant"].replace("cold_v1_", "")
            track_label = {
                "b2b_panel": "🏪 Panel B2B",
                "private_label": "🏭 Private Label",
                "both": "🔀 Obie ścieżki",
            }.get(track, track)
            title_parts.append(track_label)
        title = " | ".join(title_parts)

        with st.expander(title):
            if in_edit_mode:
                _render_draft_editor(d, provider, model)
            else:
                _render_draft_view(d, selected_campaign_id, wp_ok)


def _render_draft_view(d: dict, selected_campaign_id: int | None, wp_ok: bool) -> None:
    """Standardowy widok draftu: preview + 4 buttons (Zatwierdź/Odrzuć/Wyślij/Edytuj)."""
    draft_id = d["id"]
    st.text(d["preview"] or "(brak treści)")
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("✅ Zatwierdź", key=f"approve-{draft_id}"):
        with SessionLocal() as session:
            obj = session.get(EmailDraft, draft_id)
            obj.status = DraftStatus.APPROVED.value
            session.commit()
        st.rerun()
    if c2.button("❌ Odrzuć", key=f"reject-{draft_id}"):
        with SessionLocal() as session:
            obj = session.get(EmailDraft, draft_id)
            obj.status = DraftStatus.REJECTED.value
            session.commit()
        st.rerun()
    send_disabled = (
        not wp_ok or selected_campaign_id is None or settings.dry_run
    )
    if c3.button(
        "📤 Wyślij",
        key=f"send-{draft_id}",
        disabled=send_disabled,
        help=(
            "DRY_RUN=true - wysyłka zablokowana" if settings.dry_run
            else "Brak kampanii do wysłania" if selected_campaign_id is None
            else "Push do Woodpeckera, start sekwencji follow-upów"
        ),
        type="primary",
    ):
        try:
            from agent.push_to_sender import push_draft
            with st.spinner(f"Wysyłam draft #{draft_id} do Woodpecker..."):
                prospect_id = push_draft(draft_id, selected_campaign_id)
            st.success(
                f"✅ Wysłany do Woodpecker (prospect_id={prospect_id or '?'}). "
                f"Sekwencja follow-upów aktywna."
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Wysyłka padła: {exc}")
    if c4.button("✏️ Edytuj", key=f"edit-{draft_id}"):
        st.session_state[f"edit_mode_{draft_id}"] = True
        # Pre-seed edit field values z aktualnym stanem DB
        for field in ("subject", "snippet1", "snippet2", "snippet3", "snippet4", "snippet5"):
            st.session_state[f"edit_{field}_{draft_id}"] = d[field] or ""
        st.rerun()


def _assemble_draft_text(
    subject: str, s1: str, s2: str, s3: str, s4: str | None, s5: str
) -> str:
    """Compose body text dla podglądu/zapisu. None i pusty snippet4 dopuszczalny."""
    parts = [f"Subject: {subject}", "", s1, "", s2, "", s3]
    if s4 and s4.strip():
        parts.extend(["", s4])
    parts.extend(["", s5])
    return "\n".join(parts)


def _render_draft_editor(d: dict, provider: str, model: str) -> None:
    """Tryb edycji: text inputs per pole + regenerate buttons + Save/Cancel."""
    draft_id = d["id"]

    st.caption(
        "💡 Edytujesz draft ręcznie. Po zapisie zostanie oznaczony jako 'edytowany'. "
        "Możesz też wygenerować alternatywną wersję każdego pola przyciskiem 🎲."
    )

    def _field_row(label: str, field_name: str, height: int | None = None) -> str:
        col_input, col_regen = st.columns([5, 1])
        key = f"edit_{field_name}_{draft_id}"
        if height is None:
            value = col_input.text_input(label, key=key)
        else:
            value = col_input.text_area(label, key=key, height=height)
        if col_regen.button(
            "🎲 Inna",
            key=f"regen_{field_name}_{draft_id}",
            help=f"Wygeneruj alternatywną wersję dla {field_name} (LLM call ~$0.001)",
        ):
            try:
                from agent.generate import regenerate_snippet
                with st.spinner(f"Generuję alternatywę dla {field_name}..."):
                    new_text = regenerate_snippet(
                        draft_id, field_name,
                        provider=provider, model=model,
                    )
                st.session_state[key] = new_text
                st.rerun()
            except Exception as exc:
                st.error(f"Regeneracja padła: {exc}")
        return value

    new_subject = _field_row("📨 Subject", "subject")
    new_s1 = _field_row("Otwarcie (snippet1)", "snippet1", height=80)
    new_s2 = _field_row("Most do oferty (snippet2)", "snippet2", height=80)
    new_s3 = _field_row("Propozycja wartości (snippet3)", "snippet3", height=100)
    new_s4 = _field_row("Social proof (snippet4, opcjonalny)", "snippet4", height=80)
    new_s5 = _field_row("CTA (snippet5)", "snippet5", height=80)

    st.markdown("**Podgląd po edycji:**")
    st.text(_assemble_draft_text(new_subject, new_s1, new_s2, new_s3, new_s4 or None, new_s5))

    sc1, sc2 = st.columns([1, 1])
    if sc1.button("💾 Zapisz zmiany", key=f"save_{draft_id}", type="primary"):
        try:
            _save_draft_edits(
                draft_id, new_subject, new_s1, new_s2, new_s3,
                new_s4 or None, new_s5,
            )
            st.session_state.pop(f"edit_mode_{draft_id}", None)
            # Wyczyść field cache żeby przy kolejnym Edytuj re-seedowało z DB
            for f in ("subject", "snippet1", "snippet2", "snippet3", "snippet4", "snippet5"):
                st.session_state.pop(f"edit_{f}_{draft_id}", None)
            st.success("Zmiany zapisane.")
            st.rerun()
        except Exception as exc:
            st.error(f"Zapis padł: {exc}")
    if sc2.button("❌ Anuluj", key=f"cancel_{draft_id}"):
        st.session_state.pop(f"edit_mode_{draft_id}", None)
        for f in ("subject", "snippet1", "snippet2", "snippet3", "snippet4", "snippet5"):
            st.session_state.pop(f"edit_{f}_{draft_id}", None)
        st.rerun()


def _save_draft_edits(
    draft_id: int,
    subject: str,
    s1: str, s2: str, s3: str,
    s4: str | None, s5: str,
) -> None:
    """Persist edits: scrub AI artifacts + rebuild full_preview + flag edited."""
    from agent.generate import _strip_ai_artifacts

    def _clean(t: str | None) -> str | None:
        if t is None:
            return None
        cleaned = _strip_ai_artifacts(t)
        # _strip_ai_artifacts może zwrócić "" gdy wszystko było clichém - zachowaj original wtedy
        return cleaned if cleaned else t

    clean_subject = _clean(subject) or subject
    clean_s1 = _clean(s1) or s1
    clean_s2 = _clean(s2) or s2
    clean_s3 = _clean(s3) or s3
    clean_s4 = _clean(s4) if s4 and s4.strip() else None
    clean_s5 = _clean(s5) or s5

    with SessionLocal() as session:
        draft = session.get(EmailDraft, draft_id)
        if draft is None:
            raise ValueError(f"Draft #{draft_id} zniknął.")
        draft.subject = clean_subject
        draft.snippet1 = clean_s1
        draft.snippet2 = clean_s2
        draft.snippet3 = clean_s3
        draft.snippet4 = clean_s4
        draft.snippet5 = clean_s5
        draft.full_preview = _assemble_draft_text(
            clean_subject, clean_s1, clean_s2, clean_s3, clean_s4, clean_s5,
        )
        draft.edited_by_user = True
        session.add(
            Event(
                level="INFO",
                source="gui",
                type="draft_edited",
                message=f"Draft #{draft_id} edited by user via GUI",
            )
        )
        session.commit()


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


# Sidebar: branding + nav + model picker
_render_sidebar_nav()
selected_provider, selected_model = _render_llm_selector()

# Sidebar foot: cost meter używając daily_research_limit jako "kredytów"
# (każdy researched lead = ~1 kredyt na potrzeby UX). Lokalny resetuje się
# o północy UTC.
from sqlalchemy import select as _select_for_dashboard
with SessionLocal() as _s:
    _today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    _credits_used = _s.scalar(
        _select_for_dashboard(func.count(Lead.id)).where(
            Lead.created_at >= _today_start,
            Lead.status != LeadStatus.NEW.value,
        )
    ) or 0
sb_foot(
    credits_used=int(_credits_used),
    credits_total=int(settings.daily_research_limit) or 100,
    renews_label="jutro 02:00 PL",
)

# ─── Topbar: breadcrumbs + search + buttons + avatar ─────────────────────
owner_initials = "".join([p[0].upper() for p in (settings.owner_name or "MK").split()[:2]]) or "EC"
topbar(
    crumbs=["Workspace", settings.company_name or "Artmaker", "Agenci AI", "Handlowiec"],
    user_initials=owner_initials,
)

# ─── Page head: tytuł + time range picker po prawej ──────────────────────
page_head(
    "Handlowiec cold-email",
    subtitle=f"model {selected_provider}/{selected_model}",
    last_update="właśnie",
    right_widget=time_range_html(["24h", "7d", "30d", "90d", "YTD"], active="30d"),
)

tab_dashboard, tab_discovery, tab_leads, tab_drafts, tab_logs = st.tabs(
    ["Pulpit", "Pozyskiwanie", "Leady", "Drafty", "Logi"]
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
