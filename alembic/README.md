# Alembic migrations

Wersjonowane migracje schematu DB. Zastępują stopniowo
`_migrate_workspace_columns()` z `core/db.py` (które zostaje jako bootstrap
fallback dla dev SQLite).

## Pierwsze uruchomienie

### Lokalnie (nowa SQLite od zera)

    alembic upgrade head

Tworzy wszystkie tabele + indeksy z `core/db.py` modeli.

### Produkcja Railway (istniejąca baza Postgres z init_db)

Jednorazowo, aby Alembic uznał obecny stan za "current":

    alembic stamp head

To NIE wykonuje DDL — tylko zapisuje w tabeli `alembic_version` że
migracja `head` jest aplikowana. Od tego momentu kolejne migracje
działają normalnie (`alembic upgrade head` po każdym deploy).

## Codzienne użycie

### Nowa zmiana schematu

1. Edytuj model w `core/db.py` (dodaj kolumnę / tabelę / index)
2. Wygeneruj revision:

       alembic revision --autogenerate -m "krotki_opis"

3. Otwórz wygenerowany plik w `alembic/versions/` i:
   - Sprawdź `upgrade()` / `downgrade()` (autogenerate czasem gubi szczegóły)
   - Dodaj guard `if column not in ...` jeśli to też w `_migrate_workspace_columns`
4. `alembic upgrade head` lokalnie aby przetestować
5. Commit, push, Railway sam zaaplikuje przy starcie (po dodaniu do CMD).

### Rollback ostatniej migracji

    alembic downgrade -1

### Stan biezacy

    alembic current
    alembic history

## Auto-apply przy deploy

W produkcji powinno odpalać się `alembic upgrade head` w startup script
backendu (przed `uvicorn`). Tymczasowo nie jest to wpięte — robi to ręcznie
przez `railway run alembic upgrade head` po każdej zmianie schematu.

Po stamp'ie produkcji można wpiąć na stałe — wtedy Railway sam migrować
będzie przy każdym deploy.
