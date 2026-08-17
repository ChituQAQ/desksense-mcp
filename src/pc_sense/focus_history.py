"""焦点窗口历史（SQLite）。

后台 focus monitor 每秒检查一次前台窗口，仅当进程/标题/窗口身份
发生变化时才结束上一条、创建下一条记录。轻量保留策略：只保留最近
N 天数据。数据库开启 WAL 模式。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS focus_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    process_name TEXT,
    pid INTEGER,
    window_title TEXT
);
CREATE INDEX IF NOT EXISTS idx_focus_events_started ON focus_events (started_at);
"""


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


class FocusHistory:
    """SQLite 焦点历史存储 + 轻量后台 monitor。

    线程安全：所有写入通过单个写锁。
    """

    def __init__(self, db_path: Path, retention_days: int = 30):
        self.db_path = Path(db_path)
        self.retention_days = max(1, int(retention_days))
        self._lock = threading.Lock()
        self._db: Optional[sqlite3.Connection] = None
        self._last_event_id: Optional[int] = None
        self._last_key: Optional[tuple] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._open_connection()

    # ---------- 存储 ----------
    def _open_connection(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        # 打开日志：可用 → 合适并发，参考 SQLite
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        try:
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        conn.executescript(_SCHEMA)
        # 恢复未闭合事件：启动时给所有 ended_at IS NULL 的事件打上结束时间
        try:
            conn.execute(
                "UPDATE focus_events SET ended_at = ? WHERE ended_at IS NULL",
                (_iso(time.time()),),
            )
            conn.commit()
        except Exception:
            pass
        self._db = conn

    def _load_last_event(self) -> Optional[Dict[str, Any]]:
        if self._db is None:
            return None
        cur = self._db.execute(
            "SELECT id, started_at, ended_at, process_name, pid, window_title "
            "FROM focus_events ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "started_at": row[1],
            "ended_at": row[2],
            "process_name": row[3],
            "pid": row[4],
            "window_title": row[5],
        }

    def _ensure_connection(self) -> None:
        if self._db is None:
            self._open_connection()

    # ---------- 写入 ----------
    def record_focus_change(self, key: tuple, process_name: str, pid: int, window_title: str) -> None:
        """记录一次焦点变化。

        key 形如 (process_name, pid, window_title) 或包含窗口身份。
        服务器启动时如果 key 与当前打开的记录一致则不动；否则结束旧开新。
        """
        with self._lock:
            self._ensure_connection()
            now = time.time()
            now_iso = _iso(now)
            last = self._load_last_event()
            if last is not None and last.get("ended_at") is None:
                # 对比：相同内容则延长（不结束），不同则结束旧事件
                last_key = self._last_key
                if last_key == key:
                    return
                self._db.execute(
                    "UPDATE focus_events SET ended_at = ? WHERE id = ?",
                    (now_iso, last["id"]),
                )
            self._db.execute(
                "INSERT INTO focus_events (started_at, ended_at, process_name, pid, window_title) "
                "VALUES (?, ?, ?, ?, ?)",
                (now_iso, None, process_name, pid, window_title),
            )
            self._db.commit()
            self._last_key = key
            self._last_event_id = self._db.execute("SELECT last_insert_rowid()").fetchone()[0]

    def close_open_event(self) -> None:
        """服务器关闭时安全结束最后一条 open 事件。"""
        with self._lock:
            if self._db is None:
                return
            try:
                self._db.execute(
                    "UPDATE focus_events SET ended_at = ? WHERE ended_at IS NULL",
                    (_iso(time.time()),),
                )
                self._db.commit()
            except Exception:
                pass

    def cleanup_old(self) -> None:
        """删除超过保留天数的历史。"""
        with self._lock:
            if self._db is None:
                return
            try:
                cutoff = (datetime.now() - timedelta(days=self.retention_days)).isoformat()
                self._db.execute("DELETE FROM focus_events WHERE started_at < ?", (cutoff,))
                self._db.commit()
            except Exception:
                pass

    def query(self, minutes: int = 30, limit: int = 100) -> List[Dict[str, Any]]:
        """按时间升序返回最近焦点变化（分钟窗口内）。"""
        with self._lock:
            self._ensure_connection()
            cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
            cur = self._db.execute(
                "SELECT started_at, ended_at, process_name, pid, window_title "
                "FROM focus_events WHERE started_at >= ? "
                "ORDER BY id DESC LIMIT ?",
                (cutoff, limit),
            )
            rows = cur.fetchall()
        # 倒序读回 → 需按时间升序返回
        rows = list(reversed(rows))
        return [
            {
                "started_at": r[0],
                "ended_at": r[1],
                "process_name": r[2],
                "pid": r[3],
                "window_title": r[4],
            }
            for r in rows
        ]

    # ---------- 后台 monitor ----------
    def start_monitor(self, poll_interval: float = 1.0) -> None:
        """启动后台 focus monitor 线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop, args=(poll_interval,), daemon=True, name="focus-monitor"
        )
        self._thread.start()
        logger.info("focus monitor 启动 (poll %.1fs)", poll_interval)

    def stop_monitor(self) -> None:
        """停止 monitor 并关闭打开事件。"""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self.close_open_event()

    def _monitor_loop(self, poll_interval: float) -> None:
        # 将窗口读取放到循环外 import，避免循环依赖
        from .windows_focus import get_foreground_info

        last_key: Optional[tuple] = None
        while not self._stop.is_set():
            try:
                info = get_foreground_info()
                process_name = info.get("process_name")
                pid = info.get("pid")
                title = info.get("window_title")
                if pid and process_name:
                    key = (process_name, pid, title)
                    if key != last_key:
                        self.record_focus_change(
                            key, process_name or "", pid, title or ""
                        )
                        last_key = key
            except Exception:
                logger.exception("focus monitor 周期执行失败")
            try:
                self.cleanup_old()
            except Exception:
                pass
            self._stop.wait(poll_interval)


def build_monitor_instance(cfg) -> FocusHistory:
    """工厂：从 Config 创建 FocusHistory。"""
    hist = FocusHistory(cfg.db_path, retention_days=cfg.history_retention_days)
    hist.start_monitor(cfg.focus_poll_interval)
    return hist