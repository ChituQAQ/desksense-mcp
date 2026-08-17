"""Windows 打开的桌面应用枚举（EnumWindows）。

只枚举用户真正“打开着”的可见顶层窗口：
  - 跳过不可见窗口
  - 跳过空标题窗口
  - 跳到隐藏/系统内部窗口（TryGetVisibility / cloaked 检测）
  - tool window 跳过
  - 按进程适度聚合，按窗口数量排序

单窗口读取失败不影响其它窗口。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Dict, List, Optional

import psutil

from .windows_focus import (
    UWP_SHELL_PROCESSES,
    get_window_pid,
    get_window_title,
    _proc_by_pid,
    _process_display_name,
    _get_exe_path,
)

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
kernel32 = ctypes.windll.kernel32

WS_EX_TOOLWINDOW = 0x00000080
GW_OWNER = 4
DWMWA_CLOAKED = 14

IsWindow = user32.IsWindow
IsWindowVisible = user32.IsWindowVisible
GetWindowLongW = user32.GetWindowLongW
GetWindow = user32.GetWindow


def _is_window_toolwindow(hwnd: int) -> bool:
    """判断是否为 tool window（不应算作普通桌面应用）。"""
    try:
        exstyle = GetWindowLongW(wintypes.HWND(hwnd), -20)  # GWL_EXSTYLE
        return bool(exstyle & WS_EX_TOOLWINDOW)
    except Exception:
        return False


def _is_window_ownerless(hwnd: int) -> bool:
    """owner=0 的顶层窗口（一般普通应用窗口都有 owner，弹出窗口等除外）。"""
    try:
        return GetWindow(wintypes.HWND(hwnd), GW_OWNER) == 0
    except Exception:
        return False


def _is_cloaked(hwnd: int) -> bool:
    """Windows 10+ 用 DWMWA_CLOAKED 判断窗口是否被系统隐藏（UWP）。"""
    try:
        cloaked = wintypes.DWORD()
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_CLOAKED,
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        return bool(cloaked.value)
    except Exception:
        # dwmapi 判断失败视为“不知道”，不因失败而误判可见
        return False


def _is_applicable_window(hwnd: int) -> bool:
    """窗口是否算作一个可显示的桌面应用窗口。"""
    try:
        if not IsWindow(wintypes.HWND(hwnd)):
            return False
        if not IsWindowVisible(wintypes.HWND(hwnd)):
            return False
        if _is_cloaked(hwnd):
            return False
        if _is_window_toolwindow(hwnd):
            return False
        # 无 owner 的独立弹窗忽略（很多系统弹窗、notify 属于此类）
        if not _is_window_ownerless(hwnd):
            return False
        title = get_window_title(hwnd)
        if not title:
            return False
        pid = get_window_pid(hwnd)
        if not pid:
            return False
        return True
    except Exception:
        return False


def _iter_windows() -> List[Dict[str, Any]]:
    """枚举所有顶层窗口，返回规范化条目列表。"""
    items: List[Dict[str, Any]] = []
    try:

        def cb(hwnd: int, lparam: int) -> bool:
            hwnd = int(hwnd)
            if not _is_applicable_window(hwnd):
                return True
            pid = get_window_pid(hwnd)
            title = get_window_title(hwnd)
            items.append({"hwnd": hwnd, "pid": pid, "title": title})
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
        )
        user32.EnumWindows(WNDENUMPROC(cb), wintypes.LPARAM(0))
    except Exception:
        pass
    return items


def list_open_apps(
    include_titles: bool = True,
    limit: int = 30,
    max_window_cap: int = 100,
    exclude_processes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """返回聚合后的打开桌面应用列表。

    参数:
      include_titles: 是否包含各进程的窗口标题列表
      limit: 最多返回多少个应用（进程）
      max_window_cap: 限制单进程窗口标题数量上限
      exclude_processes: 需要忽略的进程名列表
    """
    exclude = {p.lower() for p in (exclude_processes or [])}
    windows = _iter_windows()

    if exclude:
        windows = [
            w
            for w in windows
            if not _process_is_excluded(w.get("pid"), exclude)
        ]

    # 按进程聚合
    by_pid: Dict[int, Dict[str, Any]] = {}
    for w in windows:
        pid = w.get("pid")
        p = _proc_by_pid(pid) if pid else None
        name = _process_display_name(p)
        if not name:
            continue
        if name.lower() in UWP_SHELL_PROCESSES:
            # ApplicationFrameHost 类，展现它子进程名（如果有）
            name = _resolve_uwp_name(w.get("hwnd"), name)
        entry = by_pid.setdefault(
            pid,
            {
                "process_name": name,
                "pids": [pid],
                "windows": [],
                "_count": 0,
                "exe_path": None,
            },
        )
        entry["_count"] += 1
        if include_titles:
            title = w.get("title") or ""
            if title and len(entry["windows"]) < max_window_cap:
                if title not in entry["windows"]:
                    entry["windows"].append(title)

    apps: List[Dict[str, Any]] = []
    for pid, e in by_pid.items():
        if e["_count"] == 0:
            continue
        # pids 去重
        e["pids"] = sorted(set(e["pids"]))
        exe_path = _get_exe_path(pid)
        apps.append(
            {
                "process_name": e["process_name"],
                "pids": e["pids"],
                "windows": e["windows"] if include_titles else None,
                "exe_path": exe_path,
            }
        )

    # 窗口数量降序、进程名升序，取前 limit
    apps.sort(key=lambda a: (-(len(a.get("windows") or [])), a["process_name"].lower()))
    return apps[: max(1, min(limit, max_window_cap))]


def _process_is_excluded(pid: Optional[int], exclude: set) -> bool:
    if not pid or not exclude:
        return False
    p = _proc_by_pid(pid)
    if p is None:
        return False
    return _process_display_name(p).lower() in exclude


def _resolve_uwp_name(hwnd: int, fallback_name: str) -> str:
    """UWP 壳进程：尝试从其子窗口找到真实应用进程名。"""
    try:
        pid = get_window_pid(hwnd)
        if not pid:
            return fallback_name
        # 查看所有 pid 中不含壳进程名的兄弟/子窗口进程
        child_pids: set = set()
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
        )

        def cb(child: int, lparam: int) -> bool:
            child = int(child)
            cpid = get_window_pid(child)
            if cpid:
                child_pids.add(cpid)
            return True

        user32.EnumChildWindows(
            wintypes.HWND(hwnd), WNDENUMPROC(cb), wintypes.LPARAM(0)
        )
        for cpid in child_pids:
            cp = _proc_by_pid(cpid)
            cname = _process_display_name(cp)
            if cname and cname.lower() not in UWP_SHELL_PROCESSES:
                return cname
    except Exception:
        pass
    return fallback_name