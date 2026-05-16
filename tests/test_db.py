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


def test_job_types_10():
    """10 typow jobow - kazdy ma handler w worker/main.py."""
    expected = {
        "discovery_pipeline", "research_lead", "bulk_research_leads",
        "enrich_lead", "bulk_enrich_leads",
        "generate_draft", "bulk_generate_drafts",
        "send_draft", "poll_woodpecker",
        "autonomous_discovery",  # Faza 4 - autonomous discovery agent
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


def test_backfill_lead_status_cofa_drafted_bez_aktywnego_drafta():
    """REGRESSION (Hurtownia SENEKS): lead.status='drafted' ale jedyny draft
    jest REJECTED -> backfill cofa do 'researched'."""
    from core.db import _backfill_lead_status
    from web.auth import hash_password
    init_db()
    with SessionLocal() as session:
        u = User(email="bf@test.com", password_hash=hash_password("x"), name="BF")
        session.add(u)
        session.flush()
        ws = Workspace(name="BF WS", slug="bf-ws-test", owner_user_id=u.id)
        session.add(ws)
        session.flush()
        # Lead w stanie "drafted" ale jego jedyny draft jest REJECTED
        lead = Lead(
            workspace_id=ws.id, segment="sklep_papierniczy",
            company_name="Test SENEKS", website="https://test-seneks.pl",
            status=LeadStatus.DRAFTED.value, score=10.0,
        )
        session.add(lead)
        session.flush()
        draft = EmailDraft(
            workspace_id=ws.id, lead_id=lead.id,
            subject="Test", snippet1="x", snippet2="y", snippet3="z",
            snippet5="cta",
            status=DraftStatus.REJECTED.value,
        )
        session.add(draft)
        session.commit()
        lead_id = lead.id
    _backfill_lead_status()
    with SessionLocal() as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None
        assert lead.status == "researched", \
            f"Backfill nie zadzialal - status nadal {lead.status}"


def test_backfill_NIE_cofa_leada_z_aktywnym_draftem():
    """Lead drafted + ma 1 rejected + 1 aktywny draft -> NIE cofamy."""
    from core.db import _backfill_lead_status
    from web.auth import hash_password
    init_db()
    with SessionLocal() as session:
        u = User(email="bf2@test.com", password_hash=hash_password("x"), name="BF2")
        session.add(u); session.flush()
        ws = Workspace(name="BF2 WS", slug="bf2-ws-test", owner_user_id=u.id)
        session.add(ws); session.flush()
        lead = Lead(
            workspace_id=ws.id, segment="inne", company_name="HasActive",
            website="https://hasactive.pl",
            status=LeadStatus.DRAFTED.value,
        )
        session.add(lead); session.flush()
        # 1 rejected
        session.add(EmailDraft(
            workspace_id=ws.id, lead_id=lead.id, subject="A",
            snippet1="x", snippet2="y", snippet3="z", snippet5="cta",
            status=DraftStatus.REJECTED.value,
        ))
        # 1 aktywny (draft)
        session.add(EmailDraft(
            workspace_id=ws.id, lead_id=lead.id, subject="B",
            snippet1="x", snippet2="y", snippet3="z", snippet5="cta",
            status=DraftStatus.DRAFT.value,
        ))
        session.commit()
        lead_id = lead.id
    _backfill_lead_status()
    with SessionLocal() as session:
        lead = session.get(Lead, lead_id)
        # Powinien nadal byc 'drafted' bo ma aktywny draft
        assert lead.status == "drafted"


def test_backfill_NIE_rusza_stanow_finalnych():
    """SENT / REPLIED / BOUNCED to historyczne stany - backfill ich nie cofa."""
    from core.db import _backfill_lead_status
    from web.auth import hash_password
    init_db()
    with SessionLocal() as session:
        u = User(email="bf3@test.com", password_hash=hash_password("x"), name="BF3")
        session.add(u); session.flush()
        ws = Workspace(name="BF3 WS", slug="bf3-ws-test", owner_user_id=u.id)
        session.add(ws); session.flush()
        lead = Lead(
            workspace_id=ws.id, segment="inne", company_name="WasSent",
            website="https://wassent.pl",
            status=LeadStatus.SENT.value,  # historyczne, nie cofamy
        )
        session.add(lead); session.flush()
        session.add(EmailDraft(
            workspace_id=ws.id, lead_id=lead.id, subject="A",
            snippet1="x", snippet2="y", snippet3="z", snippet5="cta",
            status=DraftStatus.REJECTED.value,
        ))
        session.commit()
        lead_id = lead.id
    _backfill_lead_status()
    with SessionLocal() as session:
        lead = session.get(Lead, lead_id)
        assert lead.status == "sent"  # nie cofniete
