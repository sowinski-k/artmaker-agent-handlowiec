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

    woodpecker_api_key: str = ""
    woodpecker_campaign_id: str = ""

    google_maps_api_key: str = ""

    owner_name: str = ""
    owner_title: str = "właściciel"
    company_name: str = "Artmaker"
    company_website: str = ""

    dry_run: bool = True
    daily_email_limit: int = 30
    daily_api_budget_usd: float = 10.0
    log_level: str = "INFO"
    db_path: str = "data/leads.db"

    @property
    def db_file(self) -> Path:
        return (PROJECT_ROOT / self.db_path).resolve()

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_file}"


settings = Settings()
