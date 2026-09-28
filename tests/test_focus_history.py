"""focus_history SQLite 存储单元测试。"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from desksense.focus_history import FocusHistory


def test_insert_and_query(tmp_path):
    db = tmp_path / "test.db"
    h = FocusHistory(db, retention_days=30)
    h.record_focus_change(("a.exe", 1, "Title A"), "a.exe", 1, "Title A")
    h.record_focus_change(("b.exe", 2, "Title B"), "b.exe", 2, "Title B")
    events = h.query(minutes=30, limit=100)
    assert len(events) == 2
    assert events[0]["process_name"] == "a.exe"
    assert events[1]["process_name"] == "b.exe"
    assert events[0]["window_title"] == "Title A"
    assert events[0]["started_at"] is not None
    h.close_open_event()


def test_same_key_dedupe(tmp_path):
    db = tmp_path / "test.db"
    h = FocusHistory(db, retention_days=30)
    k = ("a.exe", 1, "Title")
    h.record_focus_change(k, "a.exe", 1, "Title")
    h.record_focus_change(k, "a.exe", 1, "Title")  # 无变化不写
    events = h.query(minutes=30, limit=100)
    assert len(events) == 1
    h.close_open_event()


def test_wal_mode(tmp_path):
    db = tmp_path / "test.db"
    h = FocusHistory(db, retention_days=30)
    h.record_focus_change(("a.exe", 1, "T"), "a.exe", 1, "T")
    import sqlite3
    conn = sqlite3.connect(str(db))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal" or mode == "WAL"
    conn.close()
    h.close_open_event()


def test_cleanup_old(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    h = FocusHistory(db, retention_days=30)
    h.record_focus_change(("a.exe", 1, "T"), "a.exe", 1, "T")
    # 伪造旧时间
    from datetime import datetime, timedelta
    old = (datetime.now() - timedelta(days=60)).isoformat()
    conn = h._db
    conn.execute("UPDATE focus_events SET started_at=? WHERE process_name='a.exe'", (old,))
    conn.commit()
    h.cleanup_old()
    events = h.query(minutes=30, limit=100)
    assert len(events) == 0
    h.close_open_event()


def test_query_includes_events_active_during_window(tmp_path):
    from datetime import datetime, timedelta

    db = tmp_path / "window.db"
    h = FocusHistory(db, retention_days=30)
    now = datetime.now()

    def insert(name, started_minutes_ago, ended_minutes_ago):
        started = (now - timedelta(minutes=started_minutes_ago)).isoformat()
        ended = (
            None
            if ended_minutes_ago is None
            else (now - timedelta(minutes=ended_minutes_ago)).isoformat()
        )
        h._db.execute(
            "INSERT INTO focus_events (started_at, ended_at, process_name, pid, window_title) "
            "VALUES (?, ?, ?, ?, ?)",
            (started, ended, name, 0, ""),
        )

    insert("still-open", 60, None)      # 开始早于窗口但仍在持续（审计缺陷场景）
    insert("ended-inside", 60, 10)      # 与最近 30 分钟存在交集
    insert("ended-before", 60, 50)      # 与最近 30 分钟无交集
    h._db.commit()

    names = [e["process_name"] for e in h.query(minutes=30, limit=100)]
    assert "still-open" in names
    assert "ended-inside" in names
    assert "ended-before" not in names
    h.close_open_event()


def test_close_releases_connection_and_stops_monitor(tmp_path, monkeypatch):
    import os

    if os.name != "nt":
        pytest.skip("monitor 依赖 windows_focus")

    monkeypatch.setattr(
        "desksense.windows_focus.get_foreground_info",
        lambda: {"pid": None, "process_name": None, "window_title": None},
    )
    db = tmp_path / "close.db"
    h = FocusHistory(db, retention_days=30)
    h.start_monitor(0.05)
    h.close()
    assert h._db is None
    assert h._thread is None or not h._thread.is_alive()
    h.close()  # 幂等