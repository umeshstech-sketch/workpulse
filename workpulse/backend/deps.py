"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import Header, HTTPException, Request

from workpulse.config import Config, get_config


def cfg() -> Config:
    return get_config()


def require_local(request: Request) -> None:
    """Laptop-only actions (settings, wipe, pairing, tokens): refused from paired phones too."""
    from workpulse.core.devices import is_loopback
    if not is_loopback(request.client.host if request.client else None):
        raise HTTPException(403, "this can only be done on the laptop")


def require_ui(x_workpulse_ui: str | None = Header(default=None)) -> None:
    """Dashboard writes must carry this header: other websites can't send it to localhost (CORS preflight)."""
    if x_workpulse_ui != "1":
        raise HTTPException(403, "missing X-WorkPulse-UI header")
