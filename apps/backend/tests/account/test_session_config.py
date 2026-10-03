"""Sessions: the API refuses to start off loopback with the dev secret or insecure cookies."""

import pytest
from pydantic import ValidationError

from backend.config import DEV_SESSION_SECRET, Settings, is_loopback_url

SECRET = "a-random-production-secret-with-enough-entropy"


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_local_development_keeps_working():
    s = settings(session_secret=DEV_SESSION_SECRET, cookie_secure=False)
    assert s.session_secret == DEV_SESSION_SECRET and s.cookie_secure is False
    settings(api_url="http://localhost:8000", frontend_url="http://[::1]:3100")


@pytest.mark.parametrize(
    "values",
    [
        {"api_url": "https://api.example.org", "session_secret": SECRET, "cookie_secure": False},
        {
            "frontend_url": "https://atlas.example.org",
            "session_secret": DEV_SESSION_SECRET,
            "cookie_secure": True,
        },
        {"api_url": "http://10.0.0.5:8000"},
    ],
)
def test_refuses_unsafe_settings_off_loopback(values):
    with pytest.raises(ValidationError) as exc:
        settings(**values)
    text = str(exc.value)
    assert "SESSION_SECRET" in text or "COOKIE_SECURE" in text
    assert SECRET not in text and DEV_SESSION_SECRET not in text


def test_production_settings_are_accepted():
    s = settings(
        api_url="https://api.example.org",
        frontend_url="https://atlas.example.org",
        session_secret=SECRET,
        cookie_secure=True,
    )
    assert s.cookie_secure is True


def test_loopback_detection():
    assert is_loopback_url("http://127.0.0.1:8000")
    assert is_loopback_url("http://127.0.0.2")
    assert is_loopback_url("http://localhost:3100")
    assert not is_loopback_url("https://127.0.0.1.example.org")
    assert not is_loopback_url("http://0.0.0.0:8000")
