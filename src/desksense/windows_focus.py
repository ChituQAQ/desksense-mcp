"""Windows 前台窗口（foreground window）感知。

使用原生 Windows API：
  GetForegroundWindow
  GetWindowText
  GetWindowThreadProcessId

处理 ApplicationFrameHost.exe / UWP 现代应用：尝试从前台窗口的子窗口
找到真正承载应用内容的后台进程。
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any, Dict, List, Optional

import psutil

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 常量
GW_HWNDNEXT = 2
GW_HWNDPREV = 3
GA_ROOTOWNER = 3
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Windows 10+ 判断 cloaked window
IsWindowVisible = user32.IsWindowVisible
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowTextW = user32.GetWindowTextW
GetForegroundWindow = user32.GetForegroundWindow
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindow = user32.GetWindow
IsWindow = user32.IsWindow
GetAncestor = user32.GetAncestor

# 已知的 UWP 包装进程：这类进程的窗口标题往往不反映真实应用。
# 真实应用信息在其子窗口或兄弟窗口中。
UWP_SHELL_PROCESSES = {
    "applicationframehost.exe",
    "shellexperiencehost.exe",
    "systemsettings.exe",
    "textinputhost.exe",
    "searchapp.exe",
    "searchhost.exe",
    "startmenuexperiencehost.exe",
}


def _win_error_context(what: str) -> str:
    """WinAPI 出错时给出简短上下文，方便排查但不崩。"""
    return f"{what} (WinAPI failure)"


def get_foreground_window() -> Optional[int]:
    """返回前台窗口句柄；理论上返回 0 表示无前台窗口。"""
    try:
        return int(GetForegroundWindow())
    except Exception:
        return None


def get_window_pid(hwnd: int) -> Optional[int]:
    """获取窗口所属进程 PID。"""
    if not hwnd:
        return None
    try:
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return None


def get_window_title(hwnd: int) -> str:
    """获取窗口标题；空窗口或失败返回空字符串。"""
    if not hwnd:
        return ""
    try:
        length = GetWindowTextLengthW(wintypes.HWND(hwnd))
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        GetWindowTextW(wintypes.HWND(hwnd), buf, length + 1)
        return buf.value.strip()
    except Exception:
        return ""


def _process_display_name(proc: Optional[psutil.Process]) -> str:
    """安全地得到进程名。"""
    try:
        if proc is None:
            return ""
        return proc.name() or ""
    except Exception:
        return ""


def _proc_by_pid(pid: int) -> Optional[psutil.Process]:
    try:
        return psutil.Process(pid)
    except Exception:
        return None


# ---------------------------------------------------------------
# 前台窗口解析
# ---------------------------------------------------------------
def get_foreground_info(include_path: bool = False) -> Dict[str, Any]:
    """获取当前前台窗口信息。

    Windows 某些情况下 GetForegroundWindow 返回 0（例如无窗口应用、
    刚启动、锁屏/桌面），此时不抛错，返回空的 foreground 结构 + error。
    """
    fg = get_foreground_window()
    if not fg:
        return {
            "timestamp": None,
            "process_name": None,
            "window_title": None,
            "pid": None,
            "exe_path": None,
            "error": "当前没有可读取的前台窗口（可能锁屏、桌面或系统无窗口应用）",
        }

    # 1) 基本读取
    hwnd: int = fg
    pid = get_window_pid(hwnd)
    title = get_window_title(hwnd)

    owner_hwnd = _resolve_owner_window(hwnd)
    owner_pid: Optional[int] = None
    owner_title: str = ""
    if owner_hwnd and owner_hwnd != hwnd:
        owner_pid = get_window_pid(owner_hwnd)
        owner_title = get_window_title(owner_hwnd)

    # 2) 确定进程
    target_pid = pid
    proc_name = ""
    exe_path = None

    p = _proc_by_pid(pid) if pid else None
    if p is not None:
        proc_name = _process_display_name(p)

    # 3) ApplicationFrameHost 处理：尝试从子窗口找真正进程
    if proc_name and proc_name.lower() in UWP_SHELL_PROCESSES:
        resolved = _resolve_uwp_from_children(hwnd)
        if resolved.get("pid"):
            target_pid = resolved["pid"]
            p2 = _proc_by_pid(target_pid)
            proc_name = _process_display_name(p2) or proc_name
            if not title and resolved.get("title"):
                title = resolved["title"]

    # exe path（可选）
    if include_path:
        exe_path = _get_exe_path(target_pid or pid)

    return {
        "timestamp": _iso_now(),
        "process_name": proc_name or None,
        "window_title": title or None,
        "pid": target_pid or pid,
        "exe_path": exe_path,
        "error": None,
    }


def _iso_now() -> str:
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


def _get_exe_path(pid: int) -> Optional[str]:
    if not pid:
        return None
    p = _proc_by_pid(pid)
    if p is None:
        return None
    try:
        return p.exe()
    except Exception:
        return None


def _get_top_level_window(hwnd: int) -> int:
    """找到窗口的根 owner 窗口（真实顶层窗口）。"""
    try:
        root = GetAncestor(wintypes.HWND(hwnd), GA_ROOTOWNER)
        return int(root)
    except Exception:
        return int(hwnd)


def _resolve_owner_window(hwnd: int) -> Optional[int]:
    """返回窗口的根 owner 窗口（或原窗口）。"""
    root = _get_top_level_window(hwnd)
    return root if root else hwnd


def _resolve_uwp_from_children(hwnd: int) -> Dict[str, Any]:
    """对 ApplicationFrameHost 类进程，枚举其子窗口找到真实应用。"""
    result: Dict[str, Any] = {"pid": None, "title": ""}
    try:

        # WNDENUMPROC 契约：回调收到 (hwnd, lparam) 两个参数。
        def cb(child: int, lparam: int) -> bool:
            child = int(child)
            # 只关心可见子窗口
            if not IsWindowVisible(wintypes.HWND(child)):
                return True
            cpid = get_window_pid(child)
            if not cpid:
                return True
            cp = _proc_by_pid(cpid)
            if cp is None:
                return True
            cname = _process_display_name(cp)
            if cname.lower() in UWP_SHELL_PROCESSES:
                return True
            child_title = get_window_title(child)
            if child_title:
                result["title"] = child_title
            result["pid"] = cpid
            return False  # 找到就停

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
        )
        EnumChildWindows = user32.EnumChildWindows
        EnumChildWindows(
            wintypes.HWND(hwnd), WNDENUMPROC(cb), wintypes.LPARAM(0)
        )
    except Exception:
        pass
    return result