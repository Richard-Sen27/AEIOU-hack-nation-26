import ipaddress
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
DEV_SESSION_SECRET = "dev-only-insecure-session-secret-change-me"


def is_loopback_url(url: str) -> bool:
    """True when the URL's host is localhost or a loopback address (local development)."""
    host = (urlsplit(url).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str = "postgresql+asyncpg://atlas_app:atlas_app@localhost:5432/atlas"
    migration_database_url: str = (
        "postgresql+psycopg://atlas_owner:atlas_owner@localhost:5432/atlas"
    )
    pipeline_database_url: str = "postgresql://atlas_pipeline:atlas_pipeline@localhost:5432/atlas"
    bootstrap_database_url: str = "postgresql://atlas:atlas@localhost:5432/postgres"

    session_secret: str = DEV_SESSION_SECRET
    session_ttl_minutes: int = 60
    cookie_secure: bool = False

    frontend_url: str = "http://127.0.0.1:3100"
    cors_extra_origin_regex: str | None = None
    api_url: str = "http://127.0.0.1:8000"
    demo_mode: bool = False

    # Gap-search agent: optional public data source keys (empty = off / unauthenticated).
    brightdata_api_key: str | None = Field(
        None, validation_alias=AliasChoices("BRIGHTDATA_API_KEY", "BRIGHT_DATA_API_KEY")
    )
    brightdata_serp_zone: str | None = None
    ncbi_api_key: str | None = None

    # Fernet key(s) for message bodies at rest, comma-separated, newest first (rotation). Separate
    # from TOKEN_ENCRYPTION_KEY. Empty: on loopback a key derived from SESSION_SECRET (demo only),
    # elsewhere messaging answers 501.
    message_encryption_key: str = ""

    # ORCID sign-in confirms a doctor's or researcher's ORCID iD (public API, scope /authenticate).
    # Real ORCID needs a registered client: ORCID_CLIENT_ID and ORCID_CLIENT_SECRET, plus
    # ORCID_BASE_URL (https://sandbox.orcid.org for testing, https://orcid.org for production).
    # ORCID_REDIRECT_URI defaults to <API_URL>/me/professional/orcid/callback and must be
    # registered with ORCID exactly. ORCID_MOCK=true switches to the simulated sign-in in
    # backend.devtools.mock_orcid (local demo only; refused unless API and frontend are loopback).
    orcid_client_id: str = ""
    orcid_client_secret: str = ""
    orcid_base_url: str = "https://orcid.org"
    orcid_redirect_uri: str = ""
    orcid_mock: bool = False

    @property
    def is_local(self) -> bool:
        """API and frontend both on loopback addresses (local development and demos)."""
        return all(is_loopback_url(u) for u in (self.api_url, self.frontend_url))

    @model_validator(mode="after")
    def _safe_outside_loopback(self) -> "Settings":
        """Refuse to start anywhere but 127.0.0.1 with the development session secret, without
        Secure cookies or with the simulated ORCID sign-in (docs/specs/system.md, Sessions).
        Names settings, never values."""
        if self.is_local:
            return self
        problems = []
        if self.orcid_mock:
            problems.append("ORCID_MOCK is on (simulated verification is local only)")
        if self.session_secret == DEV_SESSION_SECRET:
            problems.append("SESSION_SECRET is the development default")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE is false")
        if problems:
            raise ValueError(
                "API_URL or FRONTEND_URL is not a loopback address, but "
                + " and ".join(problems)
                + "; set a random SESSION_SECRET and COOKIE_SECURE=true and leave ORCID_MOCK off"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
