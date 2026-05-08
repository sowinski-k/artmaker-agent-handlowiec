import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow `streamlit run gui/app.py` to import the `core` package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from core.config import settings
from core.db import (
    DraftStatus,
    EmailDraft,
    Event,
    Lead,
    LeadStatus,
    SessionLocal,
    init_db,
)
from core.kill_switch import is_stopped, resume, stop

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


def render_leads() -> None:
    with SessionLocal() as session:
        leads = (
            session.execute(select(Lead).order_by(Lead.created_at.desc())).scalars().all()
        )
    if not leads:
        st.info(
            "Baza leadów jest pusta. Moduł `agent/research.py` jeszcze nie zaimplementowany."
        )
        return
    df = pd.DataFrame(
        [
            {
                "id": lead.id,
                "firma": lead.company_name,
                "segment": lead.segment,
                "miasto": lead.city,
                "email": lead.email,
                "score": lead.score,
                "status": lead.status,
                "dodany": lead.created_at.strftime("%Y-%m-%d"),
            }
            for lead in leads
        ]
    )
    st.dataframe(df, hide_index=True, use_container_width=True)


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
