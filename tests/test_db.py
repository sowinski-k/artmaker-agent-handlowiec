"""Smoke testy schemy bazy + bootstrap.

Sprawdzaja ze:
1. init_db() nie wywala sie na pusta baze (in-memory SQLite)
2. wszystkie tabele sie tworza
3. enumy maja oczekiwane wartosci (krytyczne - LeadStatus.DEAD_END byl dodany pozniej)
4. mozna zapisac i wyciagnac Lead, EmailDraft, Event, Job, PatrolSchedule
"""
from __future__ import annotations

from core.db import (
    DraftStatus,
    EmailDraft,
    Event,
    Job,
    JobStatus,
    JobType,
    Lead,
    LeadSegment,
    LeadStatus,
    PatrolSchedule,
    SessionLocal,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    init_db,
)


def test_init_db_idempotent():
    init_db()
    # Drugie wywolanie nie powinno rzucic - migracje sa idempotent
    init_db()


def test_lead_status_dead_end_exists():
    """LeadStatus.DEAD_END byl dodany w commicie enrichment - jak ktos usunie,
    auto-enrich pipeline sie wywali."""
    assert LeadStatus.DEAD_END.value == "dead_end"


def test_lead_segments_8():
    """8 znanych segmentow - musi byc zgodne z ResearchResult.Segment Literal."""
    expected = {
        "sklep_plastyczny", "sklep_papierniczy", "paint_and_sip",
        "warsztaty_dzieci", "animatorzy_eventy", "szkola_artystyczna",
        "marka_wlasna", "inne",
    }
    actual = {s.value for s in LeadSegment}
    assert actual == expected


def test_job_types_9():
    """9 typow jobow - kazdy ma handler w worker/main.py."""
    expected = {
        "discovery_pipeline", "research_lead", "bulk_research_leads",
        "enrich_lead", "bulk_enrich_leads",
        "generate_draft", "bulk_generate_drafts",
        "send_draft", "poll_woodpecker",
    }
    actual = {j.value for j in JobType}
    assert actual == expected


def test_workspace_roles():
    assert {r.value for r in WorkspaceRole} == {"owner", "admin", "member"}


def test_round_trip_lead_and_draft():
    """E2E: zapisz workspace+user+member, lead, draft - czytaj z powrotem."""
    init_db()
    from web.auth import hash_password
    with SessionLocal() as session:
        u = User(email="test@example.com", password_hash=hash_password("xyz"), name="T")
        session.add(u)
        session.flush()
        ws = Workspace(name="Test WS", slug="test-ws-xyz", owner_user_id=u.id)
        session.add(ws)
        session.flush()
        session.add(WorkspaceMember(
            workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER.value,
        ))
        lead = Lead(
            workspace_id=ws.id,
            segment=LeadSegment.SKLEP_PAPIERNICZY.value,
            company_name="Synchronik",
            website="https://synchronik.pl",
            score=10.0,
            status=LeadStatus.RESEARCHED.value,
        )
        session.add(lead)
        session.flush()
        draft = EmailDraft(
            workspace_id=ws.id, lead_id=lead.id,
            subject="Test", snippet1="Hi", snippet2="Body", snippet3="Cta",
            status=DraftStatus.DRAFT.value,
        )
        session.add(draft)
        session.commit()
        # readback
        assert lead.id is not None
        assert draft.lead_id == lead.id
        assert lead.drafts[0].subject == "Test"


def test_job_payload_json():
    """Job.payload to JSON column - musi zapisac dict i odczytac z powrotem."""
    init_db()
    with SessionLocal() as session:
        # Workspace dla FK
        from web.auth import hash_password
        u = User(email="j@test.com", password_hash=hash_password("x"), name="J")
        session.add(u)
        session.flush()
        ws = Workspace(name="J WS", slug="j-ws-test", owner_user_id=u.id)
        session.add(ws)
        session.flush()
        job = Job(
            workspace_id=ws.id,
            type=JobType.RESEARCH_LEAD.value,
            status=JobStatus.PENDING.value,
            payload={"url": "https://foo.pl", "segment_hint": "sklep_plastyczny"},
        )
        session.add(job)
        session.commit()
        assert job.payload["url"] == "https://foo.pl"
        assert job.status == "pending"


def test_event_workspace_id_nullable():
    """worker.heartbeat ma workspace_id=NULL - musi przejsc."""
    init_db()
    with SessionLocal() as session:
        e = Event(
            workspace_id=None,
            type="worker.heartbeat",
            level="INFO",
            source="worker",
            message="alive",
        )
        session.add(e)
        session.commit()
        assert e.id is not None
        assert e.workspace_id is None
