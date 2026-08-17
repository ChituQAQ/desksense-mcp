"""PC Sense MCP 的 7 个只读工具实现。

所有工具都是只读感知，不执行任何远程控制操作。
任何单个窗口/进程读取失败都不能导致整个工具 500。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .config import Config
from .focus_history import FocusHistory
from .system_info import get_system_info, get_top_processes
from .windows_apps import list_open_apps as _list_open_apps
from .windows_focus import get_foreground_info
from .windows_idle import get_idle_seconds, idle_state_for, get_session_locked


def _safe(fn, *args, **kwargs):
    """包裹任意工具调用，返回 (result, error)。"""
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------
# 1. pc_get_context（默认综合工具）
# ---------------------------------------------------------------
def pc_get_context(cfg: Config, history: Optional[FocusHistory] = None) -> Dict[str, Any]:
    foreground_result, fg_err = _safe(get_foreground_info)

    idle_seconds, idle_err = _safe(get_idle_seconds)
    idle_status = idle_state_for(
        idle_seconds,
        cfg.active_threshold_seconds,
        cfg.away_threshold_seconds,
    )

    open_apps, apps_err = _safe(
        _list_open_apps,
        include_titles=True,
        limit=cfg.open_apps_limit,
        max_window_cap=cfg.max_open_windows,
        exclude_processes=cfg.exclude_processes,
    )

    sys_result, sys_err = _safe(get_system_info)

    focused_apps = None
    if open_apps:
        focused_apps = [a["process_name"] for a in open_apps[:cfg.open_apps_limit]]

    return {
        "timestamp": _now_iso(),
        "foreground": foreground_result
        or {
            "process_name": None,
            "window_title": None,
            "pid": None,
            "error": fg_err or "无法读取前台窗口",
        },
        "idle": idle_status,
        "open_apps": open_apps or [],
        "system": {
            "cpu_percent": (sys_result or {}).get("cpu", {}).get("total_percent"),
            "memory_percent": (sys_result or {}).get("memory", {}).get("percent"),
            "uptime_seconds": (sys_result or {}).get("uptime_seconds"),
        },
        "note": "本工具为只读电脑感知，不具备远程控制能力。",
    }


# ---------------------------------------------------------------
# 2. pc_get_focus
# ---------------------------------------------------------------
def pc_get_focus(cfg: Config, include_path: bool = False) -> Dict[str, Any]:
    result, err = _safe(get_foreground_info, include_path=include_path)
    if err:
        return {
            "timestamp": _now_iso(),
            "process_name": None,
            "window_title": None,
            "pid": None,
            "exe_path": None,
            "error": f"获取前台窗口失败: {err}",
        }
    return result


# ---------------------------------------------------------------
# 3. pc_list_open_apps
# ---------------------------------------------------------------
def pc_list_open_apps(
    cfg: Config,
    include_titles: bool = True,
    limit: int = 30,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    result, err = _safe(
        _list_open_apps,
        include_titles=include_titles,
        limit=limit,
        max_window_cap=cfg.max_open_windows,
        exclude_processes=cfg.exclude_processes,
    )
    if err:
        return {"error": f"枚举打开应用失败: {err}", "apps": []}
    return {"apps": result or []}


# ---------------------------------------------------------------
# 4. pc_get_idle_status
# ---------------------------------------------------------------
def pc_get_idle_status(cfg: Config) -> Dict[str, Any]:
    idle_seconds, err = _safe(get_idle_seconds)
    if err:
        return {
            "error": f"获取闲置时间失败: {err}",
            "idle_seconds": None,
            "state": "unknown",
        }
    result = idle_state_for(
        idle_seconds, cfg.active_threshold_seconds, cfg.away_threshold_seconds
    )
    # 可选：锁屏判断（失败返回 None，不影响结果）
    locked = None
    try:
        locked = get_session_locked()
    except Exception:
        locked = None
    result["session_locked"] = locked
    return result


# ---------------------------------------------------------------
# 5. pc_get_pc_status
# ---------------------------------------------------------------
def pc_get_pc_status(cfg: Config) -> Dict[str, Any]:
    result, err = _safe(get_system_info)
    if err:
        return {"error": f"获取系统状态失败: {err}"}
    return result


# ---------------------------------------------------------------
# 6. pc_get_top_processes
# ---------------------------------------------------------------
def pc_get_top_processes(
    cfg: Config,
    sort_by: str = "memory",
    limit: int = 10,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 30))
    processes, err = _safe(get_top_processes, sort_by, limit)
    if err:
        return {"error": f"获取进程列表失败: {err}", "processes": []}
    return {"sort_by": sort_by, "processes": processes or []}


# ---------------------------------------------------------------
# 7. pc_get_recent_focus
# ---------------------------------------------------------------
def pc_get_recent_focus(
    cfg: Config,
    history: Optional[FocusHistory],
    minutes: int = 30,
    limit: int = 100,
) -> Dict[str, Any]:
    minutes = max(1, min(int(minutes), 1440))
    limit = max(1, min(int(limit), 500))
    if history is None:
        return {
            "error": "焦点历史未初始化",
            "events": [],
            "note": "历史数据库不可用",
        }
    try:
        events = history.query(minutes=minutes, limit=limit)
    except Exception as e:
        return {"error": f"读取焦点历史失败: {e}", "events": []}
    return {"events": events or [], "note": "事件按时间升序排列，可据此分析焦点切换"}


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")