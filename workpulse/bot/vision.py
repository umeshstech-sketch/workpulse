"""Read numbers off a phone Screen Time / Digital Wellbeing screenshot with Claude (opt-in, user-uploaded).

The image is held in memory for this one request and never written to disk or the database. The result is
returned for you to check and confirm; nothing is saved by this module.
"""
from __future__ import annotations

import base64
import json
import logging
import re

from workpulse.config import Config

log = logging.getLogger("workpulse.bot")
MAX_BYTES = 5 * 1024 * 1024
MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

PROMPT = """This should be a screenshot of a phone's screen-time screen (iOS Screen Time or Android Digital Wellbeing).
Read it and output ONLY a JSON object, no other text:
{"period": "day" | "week" | "unknown",
 "date": "YYYY-MM-DD" or null (only if a specific date is visible; "Today"/"Yesterday" -> null and set "relative"),
 "relative": "today" | "yesterday" | null,
 "total_minutes": number or null,
 "pickups": integer or null,
 "apps": [{"name": "App name as shown", "minutes": number}]}
Convert times like "1h 23m" to minutes (83). Include every app row you can read. If the image is not a
screen-time screen, output {"error": "short reason"}."""


class VisionError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise VisionError("the model didn't return JSON")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise VisionError(f"couldn't read the model's JSON ({e})") from e


def read_screen_time(cfg: Config, image: bytes, media_type: str) -> dict:
    """Returns the parsed dict (see PROMPT). Raises VisionError with a user-friendly message."""
    if media_type not in MEDIA_TYPES:
        raise VisionError("upload a PNG, JPEG, WebP or GIF screenshot")
    if len(image) > MAX_BYTES:
        raise VisionError("that image is over 5 MB; crop it or take a smaller screenshot")
    try:
        import anthropic
    except ImportError as e:
        raise VisionError("the anthropic package isn't installed") from e
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                     "data": base64.standard_b64encode(image).decode()}},
        {"type": "text", "text": PROMPT},
    ]
    kwargs: dict = dict(model=cfg.coach.model, max_tokens=4000, messages=[{"role": "user", "content": content}],
                        output_config={"effort": "low"})
    try:
        client = anthropic.Anthropic(timeout=90.0, max_retries=2)
        if cfg.coach.fallbacks:
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as e:
        raise VisionError("reading screenshots needs ANTHROPIC_API_KEY in .env (or use manual entry / CSV)") from e
    except anthropic.APIConnectionError as e:
        raise VisionError("can't reach the Anthropic API (offline?)") from e
    except anthropic.APIStatusError as e:
        raise VisionError(f"Anthropic API error {e.status_code}") from e
    except Exception as e:  # e.g. no credentials configured at all
        if "authentication" in str(e).lower():
            raise VisionError("reading screenshots needs ANTHROPIC_API_KEY in .env (or use manual entry / CSV)") from e
        raise VisionError(str(e)) from e
    if resp.stop_reason == "refusal":
        raise VisionError("the model declined to read this image")
    data = extract_json("".join(b.text for b in resp.content if b.type == "text"))
    if data.get("error"):
        raise VisionError(f"not a screen-time screenshot: {data['error']}")
    apps = [a for a in data.get("apps") or [] if isinstance(a, dict) and a.get("name") and (a.get("minutes") or 0) > 0]
    if not apps and not data.get("total_minutes"):
        raise VisionError("couldn't find any screen time in that image")
    data["apps"] = apps
    return data
