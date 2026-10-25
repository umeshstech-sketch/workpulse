"""App/window -> category, plus the privacy filter that decides what may be stored."""
from __future__ import annotations

from workpulse.config import CategoriesConfig, PrivacyConfig

PRIVATE_APP = "(private)"


def normalize_app(name: str | None) -> str | None:
    if not name:
        return None
    name = name.strip().lower()
    return name[:-4] if name.endswith(".exe") else name


def categorize(app: str | None, title: str | None, cfg: CategoriesConfig) -> str:
    app = normalize_app(app)
    t = f" {(title or '').lower()} "
    is_browser = app in cfg.browsers
    for rule in cfg.title_rules:
        if not (is_browser or rule.all_apps):
            continue
        if any(k.lower() in t for k in rule.any) and (
            not rule.and_any or any(k.lower() in t for k in rule.and_any)
        ):
            return rule.category
    if is_browser:
        return "Browsing"
    if app and app in cfg.apps:
        return cfg.apps[app]
    return cfg.default


def is_excluded(app: str | None, title: str | None, cfg: PrivacyConfig) -> bool:
    app = normalize_app(app) or ""
    if app in {normalize_app(a) for a in cfg.exclude_apps}:
        return True
    t = (title or "").lower()
    return any(k.lower() in t for k in cfg.exclude_keywords)


def scrub(app: str | None, title: str | None, cats: CategoriesConfig, privacy: PrivacyConfig) -> tuple[str | None, str | None, str]:
    """Return (app, title, category) that is safe to store, applying exclusions and the title setting.

    The raw title is used in memory to pick the category, then dropped if capture_titles is off.
    """
    if is_excluded(app, title, privacy):
        return PRIVATE_APP, None, cats.default
    category = categorize(app, title, cats)
    stored_title = title[:512] if (title and privacy.capture_titles) else None
    return normalize_app(app), stored_title, category
