"""windows_idle 状态映射单元测试。"""
import sys
from pathlib import Path

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