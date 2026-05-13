"""Alembic environment - integracja z core.db i settings.

Czyta DATABASE_URL z env (przez core.config.settings.db_url ktore robi
postgres://-> postgresql:// normalizacje). target_metadata pochodzi z
core.db.Base zeby autogenerate widzialo wszystkie modele.

Tryby:
  alembic upgrade head    -> aplikuj wszystkie pending revisions
  alembic revision -m X   -> stworz nowa rewizje (recznie)
  alembic revision --autogenerate -m X  -> wygeneruj DDL z porownania Base z DB
  alembic stamp head      -> oznacz biezacy stan jako "current" (bez DDL)
                             (uzywane raz na produkcyjnej bazie z istniejacym
                              schematem, zeby Alembic nie probowal re-tworzyc)
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Allow imports z root projektu (../) w skryptach env.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings
from core.db import Base

config = context.config

# Logging z alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Wymus URL z env (a nie z alembic.ini ktore jest puste)
config.set_main_option("sqlalchemy.url", settings.db_url)

# Target metadata - SQLAlchemy Base z core/db.py. Alembic czyta z niego
# spis tabel/kolumn/indeksow do autogenerate.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Tryb offline - generuje SQL na stdout zamiast wykonywac.

    Uzyteczne dla CI / DBA review: alembic upgrade head --sql > migrate.sql
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Tryb online - wykonuje migracje na bazie."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # wykrywa zmiany typu kolumny (VARCHAR(50) -> VARCHAR(100))
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
