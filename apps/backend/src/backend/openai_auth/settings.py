from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

DEFAULT_ISSUER = "https://auth.openai.com"
DEFAULT_API_BASE_URL = "https://api.openai.com/v1"


class OpenAISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    openai_auth_issuer: str = DEFAULT_ISSUER
    openai_api_base_url: str = DEFAULT_API_BASE_URL
    openai_client_id: str = ""
    openai_client_secret: str = ""
    openai_redirect_uri: str = "http://127.0.0.1:8000/auth/callback"
    openai_agent_name: str = "Amber Rare Disease Atlas"
    openai_agent_host_id: str = ""
    openai_model_main: str = ""
    openai_model_small: str = ""
    openai_scope: str = ""
    token_encryption_key: str = ""

    @property
    def issuer(self) -> str:
        return self.openai_auth_issuer.rstrip("/")

    @property
    def api_base_url(self) -> str:
        return self.openai_api_base_url.rstrip("/")

    @property
    def resource(self) -> str:
        """The OAuth `resource` indicator: the API base URL the tokens are valid for."""
        return self.api_base_url

    @property
    def partner_mode(self) -> bool:
        return bool(self.openai_client_id)


@lru_cache
def get_openai_settings() -> OpenAISettings:
    return OpenAISettings()
