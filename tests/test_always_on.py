"""Always-on: the supervisor's restart/backoff logic and the side panel's geometry (no real processes)."""
import time

import pytest

from workpulse.agent import control, panel, supervisor
from workpulse.config import load_config


@pytest.fixture
def sup(data_dir, monkeypatch):
    cfg = load_config()
    running: set[str] = set()
    started: list[str] = []
    monkeypatch.setattr(control, "running_pid", lambda c, name="agent": 123 if name in running else None)
    monkeypatch.setattr(control, "start_background", lambda c, name="agent", *extra: started.append(name) or 1)
    s = supervisor.Supervisor(cfg)
    s.running, s.started = running, started
    return s


def test_starts_whatever_is_not_running(sup):
    sup.running.add("agent")
    assert sup.check_once() == ["server"]
    sup.running.add("server")
    assert sup.check_once() == []


def test_backs_off_when_something_keeps_dying(sup):
    t = 1_000_000.0
    for i in range(supervisor.MAX_RESTARTS):
        assert sup.check_once(now=t + i) == ["agent", "server"]
    assert sup.check_once(now=t + 10) == []  # gave up for now
    assert sup.gave_up["agent"]
    # after the window passes it tries again
    assert sup.check_once(now=t + supervisor.WINDOW_S + 10) == ["agent", "server"]


def test_hold_pauses_restarts(sup):
    control.hold_supervisor(sup.cfg)
    assert sup.check_once() == []
    control.release_supervisor(sup.cfg)
    assert sup.check_once() == ["agent", "server"]


def test_stale_hold_is_ignored(sup):
    import os
    control.hold_supervisor(sup.cfg)
    old = time.time() - supervisor.HOLD_MAX_AGE_S - 5
    os.utime(sup.cfg.data_dir / control.HOLD_FILE, (old, old))
    assert sup.check_once() == ["agent", "server"]  # a crashed `restart` can't block it forever


def test_stop_flag_ends_the_loop(sup, monkeypatch):
    monkeypatch.setattr(control, "write_pid", lambda *a: None)
    monkeypatch.setattr(control, "clear_pid", lambda *a: None)
    monkeypatch.setattr(supervisor, "CHECK_S", 1)
    sup.running.update({"agent", "server"})
    calls = []
    orig = sup.check_once

    def once(now=None):
        calls.append(1)
        (sup.cfg.data_dir / "supervisor.stop").write_text("stop")
        return orig(now)

    sup.check_once = once
    sup.run()  # returns instead of looping forever
    assert calls == [1]


@pytest.mark.parametrize("side,expected", [("right", (1500, 0, 1920, 1032)), ("left", (0, 0, 420, 1032))])
def test_panel_rect(side, expected):
    assert panel.panel_rect((0, 0, 1920, 1032), 420, side) == expected


def test_panel_rect_never_wider_than_the_screen():
    assert panel.panel_rect((0, 0, 300, 800), 420, "right") == (0, 0, 300, 800)


def test_panel_command_passes_watch():
    assert control.command("panel", "--watch")[-2:] == ["panel", "--watch"]
    assert control.command("supervisor")[-1] == "supervise"


def test_startup_panel_settings_validate(data_dir):
    from pydantic import ValidationError

    from workpulse.config import save_settings
    cfg = save_settings({"startup": {"panel": True, "panel_side": "left", "panel_width": 500}})
    assert (cfg.startup.panel, cfg.startup.panel_side, cfg.startup.panel_width) == (True, "left", 500)
    with pytest.raises(ValidationError):
        save_settings({"startup": {"panel_width": 50}})
