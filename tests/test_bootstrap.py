"""First-install bootstrap tests."""
from __future__ import annotations

import json

import pytest

from desksense.bootstrap import ensure_api_key, update_config


def test_missing_token_is_created(tmp_path):
    token_path = tmp_path / ".secrets" / "API_KEY.txt"
    assert ensure_api_key(token_path) is True
    token = token_path.read_text(encoding="utf-8").strip()
    assert len(token) == 64
    int(token, 16)


def test_existing_valid_token_is_retained(tmp_path):
    token_path = tmp_path / ".secrets" / "API_KEY.txt"
    token_path.parent.mkdir()
    original = "a" * 64
    token_path.write_text(original + "\n", encoding="utf-8")
    assert ensure_api_key(token_path) is False
    assert token_path.read_text(encoding="utf-8").strip() == original


def test_existing_invalid_token_is_rejected(tmp_path):
    token_path = tmp_path / ".secrets" / "API_KEY.txt"
    token_path.parent.mkdir()
    token_path.write_text("not-a-token\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected format"):
        ensure_api_key(token_path)


def test_local_default_config_update(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"history_retention_days": 10}), encoding="utf-8")
    update_config(config_path, 8765, [])
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 8765
    assert data["allowed_origins"] == []
    assert data["history_retention_days"] == 10


def test_configured_origin_and_custom_port(tmp_path):
    config_path = tmp_path / "config.json"
    update_config(config_path, 18765, ["https://client.example.com"])
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["port"] == 18765
    assert data["allowed_origins"] == ["https://client.example.com"]


@pytest.mark.parametrize("port", [0, 65536])
def test_config_port_validation(tmp_path, port):
    with pytest.raises(ValueError, match="between 1 and 65535"):
        update_config(tmp_path / "config.json", port, [])
