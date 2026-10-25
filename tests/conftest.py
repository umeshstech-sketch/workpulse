import pytest

from workpulse.config import get_config


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    """Tests never call Anthropic or Twilio: no credentials, scheduler off, AI coach stubbed out."""
    for var in ("ANTHROPIC_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "META_ACCESS_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WORKPULSE_NO_SCHEDULER", "1")
    monkeypatch.setenv("MY_WHATSAPP_NUMBER", "whatsapp:+91 98765 43210")
    from workpulse.bot import coach
    monkeypatch.setattr(coach, "ask", lambda *a, **k: None)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Isolated data dir (DB, flags, settings.yaml) per test."""
    monkeypatch.setenv("WORKPULSE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("WORKPULSE_DEMO", raising=False)
    get_config.cache_clear()
    yield tmp_path
    get_config.cache_clear()
