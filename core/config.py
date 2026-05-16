from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = "anthropic"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-pro-preview"

    apify_api_token: str = ""
    apify_gmaps_actor: str = "compass~google-maps-scraper"
    # Default Allegro actor: automation-lab~allegro-scraper
    #
    # Kluczowe: ten actor przyjmuje `startUrls` (array) ze
    # zbudowanymi URL listingu Allegro - NIE `searchTerms` / `keywords`.
    # Stad poprzednie testy zwracaly defaultowe laptopy - my wysylalismy
    # ignorowane fields, actor brał fallback z example input.
    #
    # Format URL: https://allegro.pl/listing?string=<keyword>
    #          albo https://allegro.pl/kategoria/<slug>
    #
    # Stage 1 (ten actor): zwraca product-level dane z sellerLogin +
    # sellerRating. Email NIE w stage 1 (Allegro maskuje wszystkie maile
    # do @allegromail.pl - bezuzyteczne dla cold email). Email zdobywamy
    # przez osobny enrichment pipeline (Etap 2/3, jeszcze nie aktywny).
    #
    # Alternatywy do override przez ENV:
    #   parseforge~allegro-scraper      - chce startUrl (singular!), tansze
    #   klevio~allegro-seller-scraper   - wymaga URL sprzedawcy na wejsciu
    #   contactminerlabs~...email-scraper - daje email ale glownie @allegromail.pl
    apify_allegro_actor: str = "automation-lab~allegro-scraper"
    # Email enrichment - WYLACZONE w default. Maile z Allegro to aliasy
    # @allegromail.pl (proxy Allegro), bezuzyteczne dla cold mail i
    # lamia ToS Allegro. Email zdobywamy osobno przez contact_finder
    # po wzbogaceniu leada o real domene WWW.
    apify_allegro_email_actor: str = ""
    apify_linkedin_actor: str = ""
    google_places_api_key: str = ""

    woodpecker_api_key: str = ""
    woodpecker_campaign_id: str = ""

    google_maps_api_key: str = ""

    owner_name: str = ""
    owner_title: str = "właściciel"
    company_name: str = "Artmaker"
    company_website: str = ""

    dry_run: bool = True
    # Ilu draftow mozemy max pushnac do Woodpeckera w jednym dniu UTC.
    # Po naszej stronie ten cap jest ZACHOWANY tylko do przyszlych pakietow
    # subskrypcyjnych (per-account limit). Wlasciwa cadencja wysylki maili
    # JEST PO STRONIE WOODPECKERA - jego kampania ma daily sending limit
    # per mailbox + throttle + schedule godzin pracy. User pushuje 10000
    # prospects, Woodpecker je rozprowadza w czasie zgodnie z kampania.
    # Default 10000 = praktycznie bez limitu dla MVP.
    daily_email_limit: int = 10_000
    daily_research_limit: int = 100  # max nowych researchy / dzień (token guard)
    daily_api_budget_usd: float = 10.0
    log_level: str = "INFO"
    db_path: str = "data/leads.db"
    # Read DATABASE_URL env var (Railway, Heroku-style platforms set this).
    # If non-empty -> override SQLite default. SQLAlchemy auto-picks driver
    # by URL prefix (sqlite://..., postgresql://..., mysql://...).
    database_url: str = ""

    @property
    def db_file(self) -> Path:
        return (PROJECT_ROOT / self.db_path).resolve()

    @property
    def db_url(self) -> str:
        if self.database_url.strip():
            # Railway Postgres URLs come as 'postgres://' but SQLAlchemy 2.x
            # wants 'postgresql://'. Normalise.
            url = self.database_url.strip()
            if url.startswith("postgres://"):
                url = "postgresql://" + url[len("postgres://"):]
            return url
        return f"sqlite:///{self.db_file}"


settings = Settings()
