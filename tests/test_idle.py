"""windows_idle 状态映射与闲置秒数单元测试。"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from desksense.windows_idle import idle_state_for


def test_active():
    r = idle_state_for(10)
    assert r["state"] == "active"
    assert r["idle_seconds"] == 10


def test_idle_boundary():
    assert idle_state_for(59)["state"] == "active"
    assert idle_state_for(60)["state"] == "idle"
    assert idle_state_for(300)["state"] == "idle"
    assert idle_state_for(301)["state"] == "away"


def test_unknown():
    r = idle_state_for(None)
    assert r["state"] == "unknown"
    assert r["idle_seconds"] is None


def test_custom_thresholds():
    r = idle_state_for(50, active_threshold=100, away_threshold=200)
    assert r["state"] == "active"  # 50 < 100 -> active
    r2 = idle_state_for(150, active_threshold=100, away_threshold=200)
    assert r2["state"] == "idle"


class _FakeUser32:
    def __init__(self, dw_time: int):
        self._dw_time = dw_time

    def GetLastInputInfo(self, ptr) -> int:
        ptr._obj.dwTime = self._dw_time
        return 1


def _patch_idle(monkeypatch, tick: int, dw_time: int) -> None:
    import desksense.windows_idle as wi

    monkeypatch.setattr(wi, "_USER32", _FakeUser32(dw_time))
    monkeypatch.setattr(wi, "_KERNEL32", SimpleNamespace(GetTickCount=lambda: tick))


def test_idle_seconds_normal(monkeypatch):
    # 60_000 ms 前有输入
    _patch_idle(monkeypatch, tick=1_000_000_000, dw_time=999_940_000)
    import desksense.windows_idle as wi

    assert wi.get_idle_seconds() == 60


def test_idle_seconds_after_signed_tick_wrap(monkeypatch):
    # 连续开机超过 24.9 天：GetTickCount 若按有符号返回会变成负数。
    actual_tick = 2**31 + 100_000
    _patch_idle(
        monkeypatch,
        tick=actual_tick - 2**32,  # 模拟有符号返回值
        dw_time=actual_tick - 120_000,
    )
    import desksense.windows_idle as wi

    assert wi.get_idle_seconds() == 120


def test_tick_race_is_not_reported_as_huge_idle(monkeypatch):
    # 输入恰好落在两次读取之间：差值回绕成接近 2^32，应按 0 处理。
    _patch_idle(monkeypatch, tick=1_000_000_000, dw_time=1_000_000_001)
    import desksense.windows_idle as wi

    assert wi.get_idle_seconds() == 0


def test_gettickcount_restype_is_unsigned():
    import desksense.windows_idle as wi
    from ctypes import wintypes

    assert wi._KERNEL32.GetTickCount.restype == wintypes.DWORD