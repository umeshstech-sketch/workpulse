import re

from workpulse.config import ROOT

DOCS = [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))]


def test_relative_links_resolve():
    broken = []
    for md in DOCS:
        for link in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", md.read_text(encoding="utf-8")):
            if not link.startswith(("http", "mailto")) and not (md.parent / link).resolve().exists():
                broken.append(f"{md.name}: {link}")
    assert broken == []


def test_readme_screenshots_exist_and_guides_are_linked():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for shot in re.findall(r"docs/screenshots/(\w+)\.png", readme):
        assert (ROOT / "docs" / "screenshots" / f"{shot}.png").stat().st_size > 10_000
    for guide in ("setup", "whatsapp", "phone", "dashboard", "privacy", "architecture", "troubleshooting", "future-ideas"):
        assert f"docs/{guide}.md" in readme
