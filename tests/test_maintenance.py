import os
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from workpulse import cli
from workpulse.backend import app as app_module
from workpulse.bot.scheduler import daily_backup
from workpulse.config import get_config
from workpulse.core.db import upsert_sessions
from workpulse.core.maintenance import backup, list_backups, run_checks
from workpulse.core.models import SessionRecord
from workpulse.logs import tail


def seed(cfg):
    upsert_sessions(cfg.db_path, [SessionRecord(start_ts=1000, end_ts=2000, state="active", app="code", title=None, category="Coding")])


def test_backup_is_a_working_copy_and_prunes(data_dir):
    cfg = get_config()
    seed(cfg)
    first = backup(cfg, keep=2)
    con = sqlite3.connect(first)
    assert con.execute("select count(*) from activity_sessions").fetchone()[0] == 1
    con.close()
    for i in range(3):
        p = backup(cfg, keep=2)
        os.utime(p, (time.time() + i, time.time() + i))
        time.sleep(1.1)  # distinct timestamped names
    assert len(list_backups(cfg)) == 2


def test_daily_backup_only_when_stale(data_dir):
    cfg = get_config()
    seed(cfg)
    daily_backup(cfg, only_if_older_h=24)
    daily_backup(cfg, only_if_older_h=24)  # fresh one exists -> skipped
    assert len(list_backups(cfg)) == 1


def test_doctor_checks(data_dir):
    cfg = get_config()
    seed(cfg)
    checks = {c.name: c for c in run_checks(cfg)}
    assert {"Python", "Config", "Database", "Backups", "Tracker", "Dashboard", "Auto-start", "WhatsApp", "AI coach"} <= set(checks)
    assert checks["Python"].status == "ok" and checks["Database"].status == "ok"
    assert checks["Tracker"].status == "fail" and "workpulse start" in checks["Tracker"].fix  # not running in tests
    assert checks["WhatsApp"].status == "warn" and checks["AI coach"].status == "warn"
    (cfg.data_dir / "settings.yaml").write_text("tracking:\n  idle_after_s: -5\n", encoding="utf-8")
    get_config.cache_clear()
    bad = {c.name: c for c in run_checks(cfg)}["Config"]
    assert bad.status == "fail" and "settings.yaml" in bad.fix


def test_cli_errors_are_friendly_and_logged(data_dir, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["phone", "import", str(data_dir / "missing.csv")])
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "FileNotFoundError" in out and "cli.log" in out and "Traceback" not in out
    assert any("Traceback" in line for line in tail(get_config(), "cli", 50))
    with pytest.raises(FileNotFoundError):  # --debug shows the real error
        cli.main(["--debug", "phone", "import", str(data_dir / "missing.csv")])


def test_cli_backup_and_logs_commands(data_dir, capsys):
    seed(get_config())
    cli.main(["backup"])
    assert "Backed up to" in capsys.readouterr().out
    cli.main(["backup", "--list"])
    assert "workpulse-" in capsys.readouterr().out
    cli.main(["logs", "agent"])
    assert "No agent.log yet" in capsys.readouterr().out


def test_server_turns_crashes_into_readable_errors(data_dir, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(app_module, "range_stats", boom)
    client = TestClient(app_module.app, raise_server_exceptions=False)
    r = client.get("/api/day")
    assert r.status_code == 500 and "server.log" in r.json()["detail"] and "kaboom" not in r.json()["detail"]

    from sqlalchemy.exc import OperationalError

    def locked(*a, **k):
        raise OperationalError("select", {}, Exception("database is locked"))

    monkeypatch.setattr(app_module, "range_stats", locked)
    r = client.get("/api/day")
    assert r.status_code == 503 and "busy" in r.json()["detail"]
