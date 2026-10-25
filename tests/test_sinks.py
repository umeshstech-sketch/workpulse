import socket

from workpulse.agent.runner import Agent
from workpulse.agent.sinks import AutoSink
from workpulse.config import get_config
from workpulse.core.db import sessions_between
from workpulse.core.models import SessionRecord


class FakePlatform:
    name = "fake"

    def idle_seconds(self):
        return 0.0

    def active_window(self):
        return "Code.exe", "main.py"

    def is_locked(self):
        return False


class BrokenSink:
    def write(self, records):
        raise ConnectionError("backend down")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_auto_sink_falls_back_to_db_when_backend_down(data_dir):
    cfg = get_config()
    cfg.server.port = free_port()  # nothing listening
    sink = AutoSink(cfg)
    sink.write([SessionRecord(start_ts=100, end_ts=200, state="active", app="code", title=None, category="Coding")])
    assert sink.using_http is False
    assert len(sessions_between(cfg.db_path, 0, 1000)) == 1


def test_agent_buffers_to_outbox_and_recovers(data_dir):
    cfg = get_config()
    a = Agent(cfg, platform=FakePlatform(), sink=BrokenSink())
    a.tracker.feed(a.sample(1000.0))
    a.tracker.feed(a.sample(1005.0))
    a.flush()
    assert (data_dir / "outbox.jsonl").exists()

    # "Restart": a new agent with a working sink loads the outbox and delivers it.
    b = Agent(cfg, platform=FakePlatform(), sink=AutoSink(cfg))
    b.load_outbox()
    assert len(b.pending) == 1
    b.flush()
    assert not (data_dir / "outbox.jsonl").exists()
    rows = sessions_between(cfg.db_path, 0, 2000)
    assert len(rows) == 1 and rows[0].app == "code" and rows[0].category == "Coding"


def test_agent_hot_reloads_settings(data_dir):
    from workpulse.config import save_settings
    cfg = get_config()
    a = Agent(cfg, platform=FakePlatform(), sink=BrokenSink())
    a._cfg_mtime = 0  # force the check to see a change
    save_settings({"tracking": {"idle_after_s": 300}, "privacy": {"capture_titles": False}})
    a.maybe_reload_config()
    assert a.tracker.idle_after == 300 and a.tracker.keep_titles is False
