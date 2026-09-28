"""Windows 用户闲置（idle）检测。

使用 GetLastInputInfo API。
状态规则可配置：idle < 60s -> active; 60~300s -> idle; >300s -> away。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Dict, Optional


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


_USER32 = ctypes.windll.user32
_KERNEL32 = ctypes.windll.kernel32
# 默认 restype 是有符号 c_int，连续开机约 24.9 天后 tick 会变负，
# 与 DWORD 型 dwTime 相减得到极端负值。显式声明为无符号。
_KERNEL32.GetTickCount.restype = wintypes.DWORD


def get_idle_seconds() -> Optional[int]:
    """返回自上次键盘/鼠标输入以来的秒数；失败返回 None。"""
    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not _USER32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick_count = int(_KERNEL32.GetTickCount())
        # 32 位无符号差值：tick 与 dwTime 各自回绕后相减依然正确。
        diff = (tick_count - int(info.dwTime)) & 0xFFFFFFFF
        if diff >= 0x80000000:
            # 输入恰好落在两次读取之间时差值回绕成接近 2^32，按 0 处理。
            diff = 0
        return diff // 1000
    except Exception:
        return None


def idle_state_for(
    idle_seconds: int | None,
    active_threshold: int = 60,
    away_threshold: int = 300,
) -> Dict[str, Any]:
    """根据闲置秒数给出状态。

    返回:
      {"state": "active"|"idle"|"away", "thresholds": {...}}
    """
    if idle_seconds is None:
        return {
            "state": "unknown",
            "idle_seconds": None,
            "thresholds": {
                "active_less_than_seconds": active_threshold,
                "away_greater_than_seconds": away_threshold,
            },
        }
    if idle_seconds < active_threshold:
        state = "active"
    elif idle_seconds <= away_threshold:
        state = "idle"
    else:
        state = "away"
    return {
        "state": state,
        "idle_seconds": idle_seconds,
        "thresholds": {
            "active_less_than_seconds": active_threshold,
            "idle_up_to_seconds": away_threshold,
            "away_greater_than_seconds": away_threshold,
        },
    }


def get_session_locked() -> Optional[bool]:
    """尝试判断系统是否锁屏/安全桌面。

    通过检测安全桌面（Winlogon / LogonUI）进程是否存在前台窗口。
    这里使用轻量稳健的方式：若前台有窗口且其所属进程为
    LogonUI.exe / Winlogon.exe，则认为锁屏或登录界面。
    判断失败返回 None（不引入脆弱 hack）。
    """
    try:
        from .windows_focus import get_foreground_info, _proc_by_pid

        info = get_foreground_info()
        proc = (info.get("process_name") or "").lower()
        if proc in {"logonui.exe", "winlogon.exe"}:
            return True
        if info.get("pid") is None:
            return None  # 无前台窗口，无法可靠判断
        return False
    except Exception:
        return None