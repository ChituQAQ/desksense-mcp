"""config 模块单元测试。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from desksense.config import Config, load_config


def test_defaults():
    cfg = Config({})
    assert cfg.port == 8765
    assert cfg.host == "127.0.0.1"
    assert cfg.focus_poll_interval == 1.0
    assert cfg.open_apps_limit == 15
    assert cfg.history_retention_days == 30


def test_override():
    cfg = Config({"port": 9999, "open_apps_limit": 5})
    assert cfg.port == 9999
    assert cfg.open_apps_limit == 5
    # 未覆盖的保留默认
    assert cfg.host == "127.0.0.1"


def test_is_excluded_process():
    cfg = Config({"exclude_processes": ["chrome.exe", "QQ.exe"]})
    assert cfg.is_excluded_process("chrome.exe")
    assert cfg.is_excluded_process("CHROME.EXE")  # 大小写不敏感
    assert cfg.is_excluded_process("qq.exe")
    assert not cfg.is_excluded_process("notepad.exe")
    assert not cfg.is_excluded_process(None)


def test_load_config_missing(tmp_path):
    cfg = load_config(tmp_path / "missing.json")
    assert cfg.port == 8765  # 回退默认


def test_load_config_valid(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"port": 7000}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.port == 7000