"""YAML mutation safety, tested without any real Node or cloudflared process."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def move():
    path = Path(__file__).resolve().parents[1] / "scripts" / "move-config.py"
    spec = importlib.util.spec_from_file_location("move_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    tunnel_id = "11111111-2222-3333-4444-555555555555"
    credential = tunnel_id + ".json"
    (root / credential).write_text(json.dumps({"TunnelID": tunnel_id, "TunnelSecret": "fake-secret"}))
    manifest = {"tunnel_id": tunnel_id, "credentials_file": credential,
                "routes": [{"hostname": "pc.example.com", "service": "http://127.0.0.1:18765"}]}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root, manifest


@pytest.mark.parametrize("indent", ["", "  ", "    "])
def test_merge_uses_ingress_node_not_other_service_lines(move, indent):
    text = (
        "tunnel: example\ningress:\n"
        f"{indent}- service: http_status:404\n{indent}  hostname: denied.example.com\n"
        f"{indent}- hostname: '*'\n{indent}  service: http://127.0.0.1:9998\n"
        "warp-routing:\n  enabled: true\n"
    )
    config, node = move.parse_yaml(text)
    route = {"hostname": "pc.example.com", "service": "http://127.0.0.1:18765"}
    result = move.merge_config(text, config, node, [route], {})
    insertion = f"{indent}- hostname: pc.example.com\n{indent}  service: http://127.0.0.1:18765\n"
    assert result.replace(insertion, "", 1) == text
    assert result.index("denied.example.com") < result.index("pc.example.com") < result.index("hostname: '*'")


@pytest.mark.parametrize("text", [
    "ingress: &rules []\ncopy: *rules\n",
    "ingress: []\ningress: []\n",
    "originRequest:\n  httpHostHeader: PRIVATE_SENTINEL\n  httpHostHeader: other\n",
    "!!python/object/apply:os.system ['PRIVATE_SENTINEL']",
])
def test_unsafe_yaml_is_rejected_without_echoing_values(move, text):
    with pytest.raises(move.MoveError) as error:
        move.parse_yaml(text)
    assert "PRIVATE_SENTINEL" not in str(error.value)


def test_flow_sequence_merge_is_refused_without_rewriting(move):
    text = 'tunnel: example\ningress: [{service: "http_status:404"}]\n'
    config, node = move.parse_yaml(text)
    with pytest.raises(move.MoveError, match="flow-style"):
        move.merge_config(text, config, node, [{"hostname": "pc.example.com", "service": "http://localhost:18765"}], {})


def test_cloudflared_rejection_precedes_all_target_writes(move, archive, tmp_path, monkeypatch):
    root, manifest = archive
    home = tmp_path / "target"
    calls = []

    def reject(command, **kwargs):
        calls.append(command)
        assert command[1] == "tunnel"
        assert command[-2:] == ["ingress", "validate"]
        assert Path(command[3]).exists()
        return subprocess.CompletedProcess(command, 1, stdout=b"PRIVATE_SENTINEL", stderr=b"")

    monkeypatch.setattr(move.subprocess, "run", reject)
    with pytest.raises(move.MoveError, match="cloudflared rejected") as error:
        move.restore_tunnel(root / "manifest.json", root, home, cloudflared="fake-cloudflared")
    assert calls
    assert "PRIVATE_SENTINEL" not in str(error.value)
    assert not home.exists()


@pytest.mark.parametrize("default", [[], "", False, 0])
def test_invalid_origin_defaults_are_not_silently_dropped(move, archive, tmp_path, default):
    root, manifest = archive
    manifest["origin_request_defaults"] = default
    (root / "manifest.json").write_text(json.dumps(manifest))
    home = tmp_path / "target"
    with pytest.raises(move.MoveError, match="originRequest"):
        move.restore_tunnel(root / "manifest.json", root, home)
    assert not home.exists()


def test_multiple_path_routes_and_nested_settings_survive_fresh_restore(move, archive, tmp_path):
    root, manifest = archive
    manifest["routes"][0].update({"path": "^/mcp$", "originRequest": {"access": {"required": True, "audTag": ["fake-audience"]}}})
    manifest["routes"].append({"hostname": "pc.example.com", "path": "^/healthz$", "service": "http://localhost:18765"})
    manifest["origin_request_defaults"] = {"connectTimeout": "45s"}
    (root / "manifest.json").write_text(json.dumps(manifest))
    home = tmp_path / "target"
    move.restore_tunnel(root / "manifest.json", root, home)
    parsed, _ = move.parse_yaml((home / "config.yml").read_text())
    assert parsed["ingress"][:-1] == manifest["routes"]
    assert parsed["originRequest"] == manifest["origin_request_defaults"]


def test_credential_path_cannot_escape_archive(move, archive, tmp_path):
    root, manifest = archive
    manifest["credentials_file"] = "../outside.json"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(move.MoveError, match="filename"):
        move.restore_tunnel(root / "manifest.json", root, tmp_path / "target")
    assert not (tmp_path / "target").exists()


@pytest.mark.parametrize("earlier", [
    {"hostname": "*.example.com", "service": "http://localhost:9999"},
    {"path": "^/mcp$", "service": "http://localhost:9999"},
])
def test_merge_refuses_rules_that_could_shadow_the_new_hostname(move, earlier):
    text = move.dump_yaml({"ingress": [earlier, {"service": "http_status:404"}]})
    config, node = move.parse_yaml(text)
    with pytest.raises(move.MoveError, match="shadow"):
        move.merge_config(text, config, node,
                          [{"hostname": "pc.example.com", "service": "http://localhost:18765"}], {})
