"""focus_history SQLite 存储单元测试。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pc_sense.focus_history import FocusHistory


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