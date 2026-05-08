# Artmaker — Agent Handlowiec

AI-driven cold-email agent dla oferty hurtowej marki Artmaker (artykuły
plastyczne i kreatywne). Researchuje leady B2B w branżach plastycznych
i kreatywnych, generuje mocno spersonalizowane drafty w głosie właściciela,
a po ręcznej akceptacji pcha je do Woodpeckera, który zajmuje się wysyłką,
warmingiem, follow-upami i wykrywaniem odpowiedzi.

## Status

Etap szkieletu. Baza, GUI i zaślepki modułów stoją; logika agenta jeszcze
nieimplementowana.

## Stack

- Python 3.11+
- Streamlit (panel kontrolny)
- SQLAlchemy 2 + SQLite (storage)
- Anthropic SDK (research + generowanie)
- Woodpecker API (wysyłka, warming, follow-upy, reply detection)

## Setup

    python -m venv .venv
    source .venv/bin/activate          # macOS / Linux
    .venv\Scripts\activate             # Windows
    pip install -r requirements.txt
    cp .env.example .env               # i uzupełnij klucze

## GUI

    streamlit run gui/app.py

Otwiera się na http://localhost:8501.

## Moduły agenta

    python -m agent.research
    python -m agent.generate
    python -m agent.push_to_sender
    python -m agent.followup

Każdy moduł sprawdza `STOP.txt` i `DRY_RUN` zanim zrobi cokolwiek wychodzącego
na zewnątrz.

## Struktura

    core/      shared infra (config, modele DB, logger, kill switch)
    agent/     skrypty uruchamiane cyklicznie
    gui/       Streamlit dashboard
    prompts/   system prompts + few-shot examples (głos właściciela)
    data/      baza SQLite (gitignored)

## Kill switch

Plik `STOP.txt` w katalogu projektu zatrzymuje każdy moduł agenta przy
następnym uruchomieniu. Dashboard ma przycisk, który tworzy / usuwa ten plik.

## DRY_RUN

`DRY_RUN=true` w `.env` blokuje wszystkie wychodzące integracje (push do
Woodpeckera itd.). Trzymaj włączone póki iterujesz nad jakością; przełącz na
`false` dopiero gdy maile brzmią dobrze i jesteś gotów wysyłać naprawdę.
