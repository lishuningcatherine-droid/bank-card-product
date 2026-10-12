"""Environment-driven settings (documented in .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    env: Literal["dev", "test", "prod"] = Field("dev", alias="BANKREC_ENV")
    database_url: str = Field("postgresql+psycopg://bankrec:bankrec@localhost:5432/bankrec", alias="DATABASE_URL")
    api_database_url: str | None = Field(None, alias="API_DATABASE_URL")  # read-only role over prod
    contact_email: str = Field("contact@example.invalid", alias="BANKREC_CONTACT_EMAIL")
    project_url: str = Field("https://github.com/lishuningcatherine-droid/bank-card-product", alias="BANKREC_PROJECT_URL")
    web_origin: str = Field("http://localhost:3000", alias="WEB_ORIGIN")
    revalidate_url: str | None = Field(None, alias="REVALIDATE_URL")
    revalidate_secret: str | None = Field(None, alias="REVALIDATE_SECRET")
    alert_webhook_url: str | None = Field(None, alias="ALERT_WEBHOOK_URL")
    alert_webhook_secret: str | None = Field(None, alias="ALERT_WEBHOOK_SECRET")
    scheduler: Literal["worker", "github", "off"] = Field("off", alias="BANKREC_SCHEDULER")
    capture_runner_label: str = Field("local", alias="CAPTURE_RUNNER_LABEL")
    chromium_executable: str | None = Field(None, alias="BANKREC_CHROMIUM_EXECUTABLE")
    min_host_interval_s: float = Field(3.0, alias="BANKREC_MIN_HOST_INTERVAL_S")
    reviewer: str | None = Field(None, alias="BANKREC_REVIEWER")
    e2e_test_data: bool = Field(False, alias="E2E_TEST_DATA")
    rate_limit_per_minute: int = Field(30, alias="API_POST_RATE_LIMIT_PER_MINUTE")
    sentry_dsn: str | None = Field(None, alias="SENTRY_DSN")
    data_dir: Path = Field(DATA_DIR, alias="BANKREC_DATA_DIR")
    reports_dir: Path = Field(REPORTS_DIR, alias="BANKREC_REPORTS_DIR")

    @property
    def user_agent(self) -> str:
        from bankrec import __version__

        return f"bankrec/{__version__} (+{self.project_url}; {self.contact_email})"

    @property
    def allow_test_only(self) -> bool:
        return self.env != "prod" and (self.e2e_test_data or self.env == "test")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
