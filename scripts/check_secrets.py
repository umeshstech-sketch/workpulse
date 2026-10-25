"""Check what would be published to GitHub for API keys, tokens and private files. Run it before every push:

    .venv\\Scripts\\python scripts\\check_secrets.py

It scans exactly the files git would include (tracked + untracked, minus .gitignore) and exits with 1 if it finds
anything that looks like a secret, so it can also be used as a pre-commit hook.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = {
    "Anthropic API key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "Google / Gemini API key": r"AIza[0-9A-Za-z_-]{30,}|\bAQ\.[A-Za-z0-9_-]{30,}",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "Twilio Account SID": r"\bAC[0-9a-f]{32}\b",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "Private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    # NAME_KEY=value / NAME_TOKEN: "value" with a real-looking value (placeholders and empty values are fine)
    "Assigned secret": r"(?i)\b[A-Z0-9_]*(?:API_KEY|AUTH_TOKEN|ACCESS_TOKEN|APP_SECRET|SECRET_KEY|PASSWORD)\s*[=:]\s*[\"']?(?!\s|$|[\"']|<|your|xxx|pick-|changeme)[A-Za-z0-9_./+=-]{16,}",
}
PRIVATE_FILES = re.compile(r"(^|/)(\.env(\..+)?|.*\.(keystore|jks|p12|pem|db|sqlite|apk|aab|token)|local\.properties)$")
ALLOWED_FILES = {".env.example"}


def publish_list() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def main() -> int:
    try:
        files = publish_list()
    except (OSError, subprocess.CalledProcessError):
        print("git isn't available or this isn't a git repository (run `git init` first).")
        return 2
    problems: list[str] = []
    for rel in files:
        if rel not in ALLOWED_FILES and PRIVATE_FILES.search(rel):
            problems.append(f"{rel}: private file type would be published (add it to .gitignore)")
            continue
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary (images, gradle-wrapper.jar)
        for n, line in enumerate(text.splitlines(), 1):
            for name, pattern in SECRET_PATTERNS.items():
                if re.search(pattern, line):
                    problems.append(f"{rel}:{n}: looks like: {name}")
    if problems:
        print("Possible secrets found. Remove them (and rotate any real key) before pushing:\n")
        print("\n".join(f"  x {p}" for p in problems))
        return 1
    print(f"OK: no secrets found in the {len(files)} files that would be published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
