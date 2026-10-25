"""Configuration: config.yaml (behaviour) + data/settings.yaml (edits made in the dashboard) + .env (secrets).

Dashboard edits go to data/settings.yaml and are deep-merged over config.yaml, so your hand-written
config.yaml (and its comments) is never rewritten by the app.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


class TrackingConfig(BaseModel):
    sample_interval_s: float = Field(5, ge=1, le=60)
    idle_after_s: float = Field(120, ge=10)
    away_after_s: float = Field(600, ge=30)
    flush_interval_s: float = Field(15, ge=5, le=300)


class PrivacyConfig(BaseModel):
    capture_titles: bool = True
    exclude_apps: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class ScoringConfig(BaseModel):
    productive_categories: list[str] = Field(
        default_factory=lambda: ["Coding", "Learning/AI", "Design", "Content Creation"]
    )
    daily_target_min: float = Field(240, gt=0)
    streak_break_tolerance_min: float = Field(3, ge=0)
    streak_target_min: float = Field(90, gt=0)
    min_break_min: float = Field(5, ge=0)


class TitleRule(BaseModel):
    any: list[str]
    and_any: list[str] = Field(default_factory=list)
    category: str
    all_apps: bool = False


class CategoriesConfig(BaseModel):
    default: str = "Other"
    browsers: list[str] = Field(default_factory=list)
    apps: dict[str, str] = Field(default_factory=dict)
    title_rules: list[TitleRule] = Field(default_factory=list)


class AgentConfig(BaseModel):
    # auto: send to the backend, and if it's not running write straight to the local DB (nothing gets stuck)
    # http: backend only (buffered to data/outbox.jsonl while it's down) · direct: local DB only
    mode: Literal["auto", "http", "direct"] = "auto"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"  # the laptop's own address for the dashboard
    port: int = 8787
    # Let paired phones on your home Wi-Fi connect (mobile app). Off = laptop only. Phones must pair with a
    # 6-digit code first, and every request then needs that phone's token. Toggle with `workpulse lan on|off`.
    lan: bool = False
    # Reach WorkPulse when you're out, over Tailscale (a private network between your own devices; nothing is
    # exposed to the internet). Only Tailscale addresses are let in, and phones still need their pairing token.
    # Toggle with `workpulse remote on|off`.
    remote: bool = False

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def bind_host(self) -> str:
        return "0.0.0.0" if self.lan or self.remote else self.host


class ScheduleConfig(BaseModel):
    morning: str = "08:00"  # HH:MM, 24h, local time. Empty string = off.
    midday: str = "13:30"
    night: str = "21:30"
    weekly: str = "sun 19:00"  # "<mon..sun> HH:MM"


class NudgeConfig(BaseModel):
    enabled: bool = True
    entertainment_min: float = 60  # nudge each time today's Entertainment crosses a multiple of this
    idle_min: float = 120  # nudge if the laptop is on but unused this long during work hours (0 = off)
    work_hours: tuple[str, str] = ("10:00", "20:00")
    quiet_hours: tuple[str, str] = ("23:00", "07:30")  # nothing proactive in here except scheduled reports
    task_reminder_hours: float = 24  # remind once when a task is due within this many hours


class WhatsAppConfig(BaseModel):
    enabled: bool = True
    provider: Literal["twilio", "meta", "console"] = "twilio"
    # Public base URL of your tunnel (e.g. https://abc.ngrok-free.app). Optional: if empty, it's rebuilt
    # from the forwarded headers. Used only to verify Twilio's request signature.
    public_url: str = ""
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    nudges: NudgeConfig = Field(default_factory=NudgeConfig)


class CoachConfig(BaseModel):
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"  # short WhatsApp texts don't need more
    max_tokens: int = 4000
    fallbacks: bool = True  # re-run a (rare) safety false positive on Anthropic's recommended fallback model


class PhoneConfig(BaseModel):
    default_device: str = "phone"
    # Substring (lowercase) of the app name or package -> category. First match wins; unmatched -> Other.
    apps: dict[str, str] = Field(default_factory=dict)


class StartupConfig(BaseModel):
    panel: bool = False  # also open the docked side panel at login (`workpulse autostart on --panel`)
    panel_side: Literal["right", "left"] = "right"
    panel_width: int = Field(420, ge=320, le=900)  # in screen points (scaled for your display)
    panel_dock: bool = True  # reserve the screen edge like the taskbar, so maximized windows don't cover it


CATEGORIES = ["Coding", "Learning/AI", "Design", "Content Creation", "Communication", "Browsing", "Entertainment", "Other"]


class Config(BaseModel):
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    categories: CategoriesConfig = Field(default_factory=CategoriesConfig)
    app_aliases: dict[str, str] = Field(default_factory=dict)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    coach: CoachConfig = Field(default_factory=CoachConfig)
    phone: PhoneConfig = Field(default_factory=PhoneConfig)
    startup: StartupConfig = Field(default_factory=StartupConfig)

    @property
    def data_dir(self) -> Path:
        return data_dir()

    @property
    def demo(self) -> bool:
        """Demo mode reads/writes a separate demo.db so fake data never mixes with your real data."""
        return os.environ.get("WORKPULSE_DEMO", "") not in ("", "0", "false")

    @property
    def db_path(self) -> Path:
        return self.data_dir / ("demo.db" if self.demo else "workpulse.db")

    @property
    def pause_flag(self) -> Path:
        return self.data_dir / "paused.flag"

    @property
    def pid_file(self) -> Path:
        return self.data_dir / "agent.pid"

    @property
    def log_dir(self) -> Path:
        d = self.data_dir / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def alias(self, app: str | None) -> str:
        if not app:
            return "-"
        return self.app_aliases.get(app, app)


def data_dir() -> Path:
    d = Path(os.environ.get("WORKPULSE_DATA_DIR") or ROOT / "data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return Path(os.environ.get("WORKPULSE_CONFIG") or ROOT / "config.yaml")


def settings_path() -> Path:
    return data_dir() / "settings.yaml"


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_config(path: Path | None = None) -> Config:
    data = _read_yaml(path or config_path())
    if path is None:
        data = deep_merge(data, _read_yaml(settings_path()))
    return Config.model_validate(data)


def save_settings(changes: dict[str, Any]) -> Config:
    """Merge `changes` into data/settings.yaml after validating the result. Raises pydantic.ValidationError."""
    overrides = deep_merge(_read_yaml(settings_path()), changes)
    cfg = Config.model_validate(deep_merge(_read_yaml(config_path()), overrides))
    settings_path().write_text(yaml.safe_dump(overrides, sort_keys=False, allow_unicode=True), encoding="utf-8")
    get_config.cache_clear()
    return cfg


def config_mtime() -> float:
    """Latest modification time of the config sources (the agent polls this to hot-reload)."""
    return max((p.stat().st_mtime for p in (config_path(), settings_path()) if p.exists()), default=0.0)


_cache: tuple[float, Config] | None = None


def get_config() -> Config:
    """The current config, re-read whenever config.yaml or data/settings.yaml changes on disk, so a change made
    by another process (e.g. `workpulse remote on` while the dashboard runs) applies without a restart."""
    global _cache
    mtime = config_mtime()
    if _cache is None or _cache[0] != mtime:
        _cache = (mtime, load_config())
    return _cache[1]


def _clear_config_cache() -> None:
    global _cache
    _cache = None


get_config.cache_clear = _clear_config_cache  # type: ignore[attr-defined]
