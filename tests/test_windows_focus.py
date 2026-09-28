"""windows_focus UWP 子窗口解析单元测试（全部 mock，不触碰真实桌面 API）。"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class _FakeProc:
    def __init__(self, name: str):
        self._name = name

    def name(self) -> str:
        return self._name


def test_uwp_child_callback_receives_hwnd_and_lparam(monkeypatch, capsys):
    if os.name != "nt":
        pytest.skip("windows_focus 依赖 user32")
    import desksense.windows_focus as wf

    def fake_enum_children(parent, callback, lparam):
        # Win32 契约：WNDENUMPROC 以 (hwnd, lparam) 两个参数被调用。
        callback(4242, 0)
        return 1

    monkeypatch.setattr(wf.user32, "EnumChildWindows", fake_enum_children)
    monkeypatch.setattr(wf, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(wf, "get_window_pid", lambda hwnd: 4242)
    monkeypatch.setattr(wf, "_proc_by_pid", lambda pid: _FakeProc("notepad.exe"))
    monkeypatch.setattr(wf, "get_window_title", lambda hwnd: "Doc - Notepad")

    result = wf._resolve_uwp_from_children(1)

    assert result["pid"] == 4242
    assert result["title"] == "Doc - Notepad"
    assert "TypeError" not in capsys.readouterr().err
