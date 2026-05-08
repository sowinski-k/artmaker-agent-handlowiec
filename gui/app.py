import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow `streamlit run gui/app.py` to import the `core` package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

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

SEGMENT_VALUES: list[str] = [s.value for s in LeadSegment]

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


def _render_manual_entry_form() -> None:
    with st.expander("Dodaj leada (researchuj URL)", expanded=False):
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
            submitted = st.form_submit_button("Researchuj", type="primary")

        if submitted:
            if not url.strip():
                st.warning("Podaj URL.")
                return
            seg = None if segment_hint == "(pozwól agentowi wybrać)" else segment_hint
            with st.status("Researchuję leada...", expanded=True) as status:
                try:
                    status.write("Pobieram treść strony i podstrony (kontakt, o nas, oferta)...")
                    status.write("Wysyłam do Claude'a do oceny według rubryki...")
                    lead_id, result = research_and_save(
                        url.strip(),
                        segment_hint=seg,
                        city_hint=city_hint.strip() or None,
                    )
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


def render_leads() -> None:
    _render_manual_entry_form()

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

            del_col, _ = st.columns([1, 5])
            if del_col.button("Usuń leada", key=f"delete-lead-{lead.id}"):
                with SessionLocal() as s:
                    obj = s.get(Lead, lead.id)
                    if obj is not None:
                        s.delete(obj)
                        s.commit()
                st.rerun()

    if len(filtered) > 20:
        st.caption(f"...i {len(filtered) - 20} więcej (zawęź filtrami).")


def render_drafts() -> None:
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
        st.info("Brak draftów do review. Uruchom `agent/generate.py` gdy będzie gotowy.")
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


st.title("Artmaker — Agent Handlowiec")
st.caption(
    f"Firma: {settings.company_name} • "
    f"Właściciel: {settings.owner_name or '(uzupełnij OWNER_NAME w .env)'}"
)

tab_dashboard, tab_leads, tab_drafts, tab_logs = st.tabs(
    ["Dashboard", "Leady", "Drafty", "Logi"]
)

with tab_dashboard:
    render_dashboard()

with tab_leads:
    render_leads()

with tab_drafts:
    render_drafts()

with tab_logs:
    render_logs()
