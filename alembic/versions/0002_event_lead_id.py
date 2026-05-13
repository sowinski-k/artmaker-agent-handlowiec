"""Event.lead_id + index dla timeline per-lead.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-13

Pod timeline w drawer'ze lead'a (omowienie: klik leada -> historia eventow).
Bez tej kolumny eventy lecialy w payload JSON i filter byl wolny na Postgres
bez funkcjonalnego indeksu.

Idempotent: ALTER TABLE z try/except (kolumna moze juz byc dorzucona przez
_migrate_workspace_columns na produkcji - ten kod tez ja dodaje, by zachowac
backward-compat dopoki produkcja nie zostanie stamp'owana na 0001).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sprawdz czy kolumna juz istnieje (mogla byc dodana przez init_db
    # bootstrap fallback w starszej wersji kodu).
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("events")]
    if "lead_id" not in cols:
        op.add_column(
            "events",
            sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=True),
        )
    indexes = [ix["name"] for ix in inspector.get_indexes("events")]
    if "ix_events_lead_id" not in indexes:
        op.create_index("ix_events_lead_id", "events", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_events_lead_id", table_name="events")
    op.drop_column("events", "lead_id")
