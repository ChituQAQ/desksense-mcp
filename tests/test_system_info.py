"""system_info 进程 CPU 采样单元测试（全部假 psutil，不做真实系统调用）。"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psutil

import desksense.system_info as si


class _FakeProcess:
    def __init__(self, pid, name, cpu_sequence):
        self.info = {"pid": pid, "name": name}
        self._cpu_sequence = cpu_sequence
        self.samples = 0

    def cpu_percent(self, interval=None):
        self.samples += 1
        index = min(self.samples - 1, len(self._cpu_sequence) - 1)
        return self._cpu_sequence[index]

    def memory_info(self):
        return SimpleNamespace(rss=300 * 1024 * 1024)

    def memory_percent(self):
        return 12.5


def _patch_psutil(monkeypatch, processes):
    calls = {"constructed": []}

    def fake_process(pid):
        calls["constructed"].append(pid)
        return processes[0]

    fake = SimpleNamespace(
        process_iter=lambda attrs: iter(processes),
        cpu_percent=lambda interval=None: 0.0,
        Process=fake_process,
        AccessDenied=psutil.AccessDenied,
        ZombieProcess=psutil.ZombieProcess,
        NoSuchProcess=psutil.NoSuchProcess,
    )
    monkeypatch.setattr(si, "psutil", fake)
    monkeypatch.setattr(si.time, "sleep", lambda seconds: None)
    return calls


def test_top_processes_cpu_reuses_sampling_baseline(monkeypatch):
    busy = _FakeProcess(123, "fake-busy.exe", [0.0, 85.0])
    other = _FakeProcess(456, "fake-idle.exe", [0.0, 1.0])
    calls = _patch_psutil(monkeypatch, [busy, other])

    result = si.get_top_processes(sort_by="cpu", limit=10)

    assert [r["process_name"] for r in result[:2]] == ["fake-busy.exe", "fake-idle.exe"]
    assert result[0]["cpu_percent"] == 85.0
    assert busy.samples == 2
    assert other.samples == 2
    # 两次采样必须复用同一批 Process 实例，否则基线丢失、恒为 0。
    assert calls["constructed"] == []
