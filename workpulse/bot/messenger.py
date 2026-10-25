"""Send to MY number via the configured provider, falling back to a dry run, and log every message locally."""
from __future__ import annotations

import logging

from workpulse.bot.providers import ConsoleProvider, SendError, get_provider, my_number, split_message
from workpulse.config import Config
from workpulse.core.store import log_message

log = logging.getLogger("workpulse.bot")


class Messenger:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        p = get_provider(cfg.whatsapp.provider)
        if not p.configured():
            if cfg.whatsapp.provider != "console":
                log.warning("WhatsApp provider %r isn't configured (.env); messages are dry-run logged only",
                            cfg.whatsapp.provider)
            p = ConsoleProvider()
        self.provider = p

    @property
    def live(self) -> bool:
        return self.provider.name != "console"

    def send(self, body: str, kind: str = "chat") -> bool:
        """Send to the owner's number. Returns True if delivered to the provider (or dry-run logged)."""
        status, error = ("sent" if self.live else "dry-run"), None
        try:
            for chunk in split_message(body):
                self.provider.send(my_number(), chunk)
        except SendError as e:
            status, error = "failed", str(e)
            log.error("WhatsApp send failed (%s): %s", kind, e)
        log_message(self.cfg.db_path, "out", body, kind=kind, status=status, error=error)
        return status != "failed"
