"""auth 模块单元测试。"""
import hmac
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pc_sense.auth import check_token, extract_bearer, generate_api_key
from pc_sense.config import Config


def _cfg_with_key(key: str) -> Config:
    cfg = Config({})
    # 用环境变量注入，避免读写磁盘
    import os
    old = os.environ.get("PC_SENSE_API_KEY")
    os.environ["PC_SENSE_API_KEY"] = key
    return cfg, old


def test_generate_api_key_length():
    k = generate_api_key()
    assert len(k) == 64
    # 只含 hex
    int(k, 16)


def test_extract_bearer():
    assert extract_bearer("Bearer abc123") == "abc123"
    assert extract_bearer("bearer xyz") == "xyz"
    assert extract_bearer("Basic abc") is None  # 非 Bearer scheme
    assert extract_bearer("Abc") is None  # 无 scheme
    assert extract_bearer(None) is None
    assert extract_bearer("") is None


def test_check_token(tmp_path, monkeypatch):
    key = generate_api_key()
    monkeypatch.setenv("PC_SENSE_API_KEY", key)
    cfg = Config({})
    assert check_token(key, cfg) is True
    assert check_token("wrong", cfg) is False
    assert check_token(None, cfg) is False
    assert check_token("", cfg) is False


def test_check_token_empty_no_key(tmp_path, monkeypatch):
    import pc_sense.auth as auth_mod
    monkeypatch.delenv("PC_SENSE_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    # 模拟无可用 key
    monkeypatch.setattr(auth_mod, "api_key_from_env_or_file", lambda cfg: None)
    cfg = Config({})
    assert check_token("anything", cfg) is False