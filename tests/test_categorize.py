from workpulse.config import ROOT, load_config
from workpulse.core.categorize import PRIVATE_APP, categorize, normalize_app, scrub

cfg = load_config(ROOT / "config.yaml")
C, P = cfg.categories, cfg.privacy


def test_normalize():
    assert normalize_app("Code.exe") == "code"
    assert normalize_app(None) is None


def test_app_mapping():
    assert categorize("Code.exe", "main.py", C) == "Coding"
    assert categorize("Spotify.exe", "x", C) == "Entertainment"
    assert categorize("unknownthing.exe", "x", C) == "Other"


def test_browser_titles_refine_category():
    assert categorize("chrome.exe", "PyTorch tutorial for beginners - YouTube - Google Chrome", C) == "Learning/AI"
    assert categorize("chrome.exe", "lofi hip hop radio - YouTube - Google Chrome", C) == "Entertainment"
    assert categorize("msedge.exe", "openai/whisper · GitHub", C) == "Coding"
    assert categorize("chrome.exe", "Some random site - Google Chrome", C) == "Browsing"


def test_title_rules_ignore_non_browsers_by_default():
    assert categorize("code.exe", "youtube_downloader.py - VS Code", C) == "Coding"


def test_privacy_exclusions():
    app, title, cat = scrub("chrome.exe", "HDFC NetBanking - Google Chrome", C, P)
    assert (app, title, cat) == (PRIVATE_APP, None, "Other")
    app, title, _ = scrub("chrome.exe", "New Tab - Google Chrome (Incognito)", C, P)
    assert app == PRIVATE_APP and title is None
    assert scrub("KeePassXC.exe", "db", C, P)[0] == PRIVATE_APP


def test_title_capture_off_still_categorizes():
    p = P.model_copy(update={"capture_titles": False})
    app, title, cat = scrub("chrome.exe", "Neural nets explained - YouTube", C, p)
    assert app == "chrome" and title is None and cat == "Learning/AI"
