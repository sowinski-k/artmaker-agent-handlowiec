"""Initial schema - snapshot core/db.py modeli.

Revision ID: 0001
Revises:
Create Date: 2026-05-13

Strategia "smooth transition":

1. Nowa, pusta baza (lokalny dev, swieża Postgres):
   alembic upgrade head
   -> tworzy wszystkie tabele + indeksy z Base.metadata

2. Istniejaca baza produkcyjna (juz ma wszystkie tabele od init_db):
   alembic stamp 0001
   -> oznacza ta migracje jako "applied" bez wykonywania DDL.
   Od tego momentu kolejne `alembic revision -m ...` beda dzialaly normalnie.

Po tym kroku init_db()._migrate_workspace_columns() staje sie "dead code"
ale zostaje przez chwile jako belt-and-suspenders. W przyszlosci usuniemy.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Stworz wszystkie tabele z core.db.Base.metadata.

    Uzywamy create_all zamiast rozpisanej listy op.create_table() bo:
    - Source of truth to core/db.py (modele SQLAlchemy)
    - Eliminuje drift miedzy modelami a "ręcznym" SQL w migracji
    - Idempotent (CREATE TABLE IF NOT EXISTS via SQLAlchemy)
    """
    from core.db import Base
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    """Rollback - usun wszystkie tabele."""
    from core.db import Base
    Base.metadata.drop_all(op.get_bind())
