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

### Wybór providera LLM

Aplikacja wspiera **Anthropic Claude** i **Google Gemini** zamiennie. Możesz
przełączać model w panelu po lewej w GUI bez restartu aplikacji.

Domyślny provider ustawia `LLM_PROVIDER` w `.env` (`anthropic` lub `gemini`).
Klucze obu providerów mogą być ustawione równolegle.

### Klucz Anthropic (Claude)

1. Załóż konto na https://console.anthropic.com, doładuj kredyty (~5 USD na start).
2. Settings → API Keys → Create Key.
3. Wklej do `.env`:

       ANTHROPIC_API_KEY=sk-ant-...

### Klucz Google Gemini

1. Załóż klucz w https://aistudio.google.com/apikey (free tier dostępny).
2. Wklej do `.env`:

       GEMINI_API_KEY=AIza...

### Źródła leadów (zakładka *Pozyskiwanie*)

Możesz włączyć dowolną kombinację — agenci uderzają w źródła równolegle, a
wyniki są deduplikowane po URL. Każde źródło jest opcjonalne.

#### Apify Google Maps Scraper (rekomendowane)

Najtańsze i najbogatsze pole danych (telefon, kategoria, rating).

1. Zarejestruj się na https://console.apify.com (free tier 5 USD/mies).
2. Settings → Integrations → API tokens → skopiuj `apify_api_token`.
3. Wklej do `.env` lub Streamlit secrets:

       APIFY_API_TOKEN=apify_api_xxx

Domyślny actor: `compass~google-maps-scraper`. Możesz zmienić przez
`APIFY_GMAPS_ACTOR=...` jeśli chcesz np. `nwua9Gu5YrADL7ZDj` (oficjalny Apify).

#### Google Places API (New)

1. https://console.cloud.google.com/google/maps-apis/api-list → włącz
   *Places API (New)* w nowym projekcie.
2. APIs & Services → Credentials → Create credentials → API key.
3. (Zalecane) ogranicz klucz do *Places API (New)* w sekcji *API restrictions*.
4. Wklej do `.env` lub Streamlit secrets:

       GOOGLE_PLACES_API_KEY=AIza...

Free tier: $200/miesiąc kredytu (~6000-8000 zapytań Text Search z naszym field mask'em).

#### Import CSV

Bez klucza, za darmo. Wgrywasz plik z kolumną `url` (wymagane). Opcjonalnie
`name`, `address`, `phone`, `notes`. Akceptuje przecinek lub średnik (Excel PL).

### Klucze na Streamlit Cloud

`.env` jest lokalny i nie wjeżdża do gita. Dla wersji wdrożonej na Streamlit
Community Cloud trzeba dodać sekrety w panelu aplikacji:

1. share.streamlit.io → Twoja aplikacja → **Settings** → **Secrets**.
2. Wklej w formacie TOML (możesz oba):

       ANTHROPIC_API_KEY = "sk-ant-..."
       GEMINI_API_KEY = "AIza..."
       # Discovery (opcjonalne, ile chcesz):
       APIFY_API_TOKEN = "apify_api_..."
       GOOGLE_PLACES_API_KEY = "AIza..."

Aplikacja zrestartuje się i pobierze sekrety przez `st.secrets`. Status klucza
(OK / brak) jest widoczny w panelu LLM po lewej.

## GUI

    streamlit run gui/app.py

Otwiera się na http://localhost:8501.

## Moduły agenta

    python -m agent.research --url https://przyklad.pl
    python -m agent.research --url https://przyklad.pl --segment paint_and_sip --city Warszawa
    python -m agent.generate
    python -m agent.push_to_sender
    python -m agent.followup

`agent.research` pobiera homepage + podstrony (kontakt / o nas / oferta),
wysyła treść do Claude'a, który ocenia lead według rubryki (5 kategorii × 0-2pkt)
i klasyfikuje do jednego z 7 segmentów. Zapisuje wynik do bazy ze statusem
`researched`. Manualnie można też dodawać przez formularz w GUI (zakładka
Leady).

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
