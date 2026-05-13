"""Lead.deleted_at - soft-delete + recycle bin.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-14

User usuwa lead -> deleted_at = utcnow(), lead znika z list/dashboard ale
zostaje w bazie 7 dni (worker auto-purge). User moze restore (deleted_at=None)
zanim auto-purge tknie.

Index ix_leads_workspace_deleted - dla trash view i worker auto-purge query.

Idempotent: kolumna i indeks mogą byc dodane przez _migrate_workspace_columns
bootstrap fallback - sprawdzamy zanim ALTER.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("leads")]
    if "deleted_at" not in cols:
        op.add_column(
            "leads",
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
    indexes = [ix["name"] for ix in inspector.get_indexes("leads")]
    if "ix_leads_workspace_deleted" not in indexes:
        op.create_index(
            "ix_leads_workspace_deleted",
            "leads",
            ["workspace_id", "deleted_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_leads_workspace_deleted", table_name="leads")
    op.drop_column("leads", "deleted_at")
