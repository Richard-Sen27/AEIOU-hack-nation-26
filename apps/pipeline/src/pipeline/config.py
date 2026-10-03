import shutil

from pydantic_settings import BaseSettings, SettingsConfigDict

from pipeline.paths import ENV_FILE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    pipeline_database_url: str = "postgresql://atlas_pipeline:atlas_pipeline@localhost:5432/atlas"
    psql_bin: str | None = None  # PSQL_BIN; defaults to psql on PATH

    ncbi_api_key: str | None = None
    omim_api_key: str | None = None
    brightdata_api_key: str | None = None

    contact_email: str = "atlas-pipeline@example.org"
    http_timeout: float = 60.0
    http_retries: int = 5
    # Requests per second per source; anything unlisted uses default_rate.
    default_rate: float = 5.0
    rates: dict[str, float] = {
        "pubmed": 3.0,
        "reporter": 1.0,
        "clinicaltrials": 5.0,
        "patient_orgs": 2.0,
        "omim": 2.0,
    }
    # HTTP cache TTL for API responses (bulk downloads are cached as files).
    cache_ttl_days: float = 30.0
    llm_concurrency: int = 8
    # Stage 4: keep a researcher only if they connect at least this many things (papers, grants,
    # trials) or link two in-scope diseases; institutions left without people are pruned.
    researcher_min_links: int = 2


settings = Settings()


def rate_for(source: str) -> float:
    if source == "pubmed" and settings.ncbi_api_key:
        return 10.0
    return settings.rates.get(source, settings.default_rate)


def psql_path() -> str:
    path = settings.psql_bin or shutil.which("psql")
    if not path:
        raise SystemExit("psql not found: install the PostgreSQL client or set PSQL_BIN")
    return path
