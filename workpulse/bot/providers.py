"""WhatsApp providers behind one small interface: Twilio (sandbox now), Meta Cloud API (later), Console (dry run).

Only official APIs are used; no WhatsApp Web scraping. Messages go ONLY to MY_WHATSAPP_NUMBER, and
inbound messages from any other number are ignored.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

log = logging.getLogger("workpulse.bot")
MAX_CHUNK = 1500  # WhatsApp allows ~1600 chars per message; split long ones on paragraph boundaries


class SendError(RuntimeError):
    pass


def digits(number: str) -> str:
    return re.sub(r"\D", "", number or "")


def my_number() -> str:
    """MY_WHATSAPP_NUMBER as bare digits with country code, e.g. 919876543210 ('' if unset or still the
    .env.example placeholder like +91XXXXXXXXXX)."""
    d = digits(os.environ.get("MY_WHATSAPP_NUMBER", ""))
    return d if len(d) >= 10 else ""


def split_message(body: str, limit: int = MAX_CHUNK) -> list[str]:
    if len(body) <= limit:
        return [body]
    parts, cur = [], ""
    for para in body.split("\n"):
        while len(para) > limit:  # a single giant line
            parts.append(para[:limit])
            para = para[limit:]
        if len(cur) + len(para) + 1 > limit:
            parts.append(cur.rstrip())
            cur = ""
        cur += para + "\n"
    if cur.strip():
        parts.append(cur.rstrip())
    return parts


class Provider(Protocol):
    name: str

    def configured(self) -> bool: ...
    def send(self, to_digits: str, body: str) -> str: ...


# ---- Twilio ------------------------------------------------------------------------------------

class TwilioProvider:
    name = "twilio"

    def __init__(self) -> None:
        self.sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        self.token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        self.from_ = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # Twilio's sandbox number

    def configured(self) -> bool:
        return bool(self.sid and self.token and my_number())

    def send(self, to_digits: str, body: str) -> str:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
        data = urllib.parse.urlencode({"From": self.from_, "To": f"whatsapp:+{to_digits}", "Body": body}).encode()
        auth = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        req = urllib.request.Request(url, data=data, method="POST", headers={"Authorization": f"Basic {auth}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read()).get("sid", "")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            hint = ""
            if "63016" in detail or "63015" in detail:
                hint = " (sandbox: message the bot / re-send your join code to reopen the session)"
            raise SendError(f"Twilio {e.code}: {detail}{hint}") from e
        except urllib.error.URLError as e:
            raise SendError(f"Twilio unreachable: {e.reason}") from e

    @staticmethod
    def signature(auth_token: str, url: str, params: dict[str, str]) -> str:
        """Twilio's X-Twilio-Signature: base64(HMAC-SHA1(token, url + sorted key/value pairs))."""
        payload = url + "".join(k + params[k] for k in sorted(params))
        return base64.b64encode(hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()).decode()

    def verify(self, url: str, params: dict[str, str], header_sig: str | None) -> bool:
        if not self.token or not header_sig:
            return False
        return hmac.compare_digest(self.signature(self.token, url, params), header_sig)


# ---- Meta WhatsApp Cloud API (for later; implemented but untested against a live account) -------

class MetaProvider:
    name = "meta"
    GRAPH = "https://graph.facebook.com/v21.0"

    def __init__(self) -> None:
        self.token = os.environ.get("META_ACCESS_TOKEN", "")
        self.phone_id = os.environ.get("META_PHONE_NUMBER_ID", "")
        self.app_secret = os.environ.get("META_APP_SECRET", "")
        self.verify_token = os.environ.get("META_VERIFY_TOKEN", "")

    def configured(self) -> bool:
        return bool(self.token and self.phone_id and my_number())

    def send(self, to_digits: str, body: str) -> str:
        req = urllib.request.Request(
            f"{self.GRAPH}/{self.phone_id}/messages", method="POST",
            data=json.dumps({"messaging_product": "whatsapp", "to": to_digits, "type": "text",
                             "text": {"body": body}}).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                msgs = json.loads(r.read()).get("messages") or [{}]
                return msgs[0].get("id", "")
        except urllib.error.HTTPError as e:
            raise SendError(f"Meta {e.code}: {e.read().decode(errors='replace')[:300]}") from e
        except urllib.error.URLError as e:
            raise SendError(f"Meta unreachable: {e.reason}") from e

    def verify(self, raw_body: bytes, header_sig: str | None) -> bool:
        if not self.app_secret or not header_sig or not header_sig.startswith("sha256="):
            return False
        expected = hmac.new(self.app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header_sig.removeprefix("sha256="))

    @staticmethod
    def parse(payload: dict) -> list[tuple[str, str]]:
        """[(from_digits, text)] for text messages in a webhook payload."""
        out = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for m in change.get("value", {}).get("messages", []) or []:
                    if m.get("type") == "text":
                        out.append((digits(m.get("from", "")), m.get("text", {}).get("body", "")))
        return out


# ---- Console (no credentials: log instead of sending) ------------------------------------------

class ConsoleProvider:
    name = "console"

    def configured(self) -> bool:
        return True

    def send(self, to_digits: str, body: str) -> str:
        log.info("[dry-run WhatsApp to +%s]\n%s", to_digits or "?", body)
        return "dry-run"


def get_provider(name: str) -> Provider:
    return {"twilio": TwilioProvider, "meta": MetaProvider, "console": ConsoleProvider}[name]()
