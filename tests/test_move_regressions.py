"""Regression cases for the September 29 review; only temporary, fake Node data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from test_move_scripts import (
    TUNNEL_ID, SAME_TUNNEL_CONFIG, make_export_node, make_restore_fixtures,
    ps_quote, run_export, run_ps, run_restore,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-only scripts")


def export_config(credential, *, options="", defaults=""):
    return (
        f"tunnel: {TUNNEL_ID}\ncredentials-file: {credential}\n"
        + defaults + "ingress:\n  - hostname: pc.example.com\n"
        + options + "    service: http://127.0.0.1:18765\n"
        "  - service: http_status:404\n"
    )


def read_export(node):
    with zipfile.ZipFile(next((node / "dist").glob("*.zip"))) as archive:
        return json.loads(archive.read("manifest.json").decode("utf-8-sig"))


@pytest.mark.parametrize("case", ["named_config", "single_quote", "external_credential"])
def test_export_supports_installed_config_and_real_credential_path(tmp_path, case):
    node, home, out = make_export_node(tmp_path / "node layout with spaces")
    cfd = home / ".cloudflared"
    credential = cfd / f"{TUNNEL_ID}.json"
    if case == "external_credential":
        external = tmp_path / "external keys" / credential.name
        external.parent.mkdir()
        credential.rename(external)
        credential = external
    # The official installer uses single-quoted YAML, including paths with spaces.
    quoted = "'" + str(credential).replace("'", "''") + "'"
    name = "desksense.yml" if case == "named_config" else "config.yml"
    (cfd / name).write_text(export_config(quoted), encoding="utf-8")
    result = run_export(node, home, out)
    assert result.returncode == 0, result.stdout + result.stderr
    assert read_export(node)["credentials_file"] == credential.name


def test_export_preserves_route_options_and_origin_defaults(tmp_path):
    node, home, out = make_export_node(tmp_path)
    cfd = home / ".cloudflared"
    credential = (cfd / f"{TUNNEL_ID}.json").as_posix()
    (cfd / "config.yml").write_text(export_config(
        credential,
        options="    path: ^/mcp$\n    originRequest:\n      httpHostHeader: internal.example.com\n",
        defaults="originRequest:\n  connectTimeout: 45s\n",
    ), encoding="utf-8")
    result = run_export(node, home, out)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = read_export(node)
    assert manifest["routes"][0]["path"] == "^/mcp$"
    assert manifest["routes"][0]["originRequest"] == {"httpHostHeader": "internal.example.com"}
    assert manifest["origin_request_defaults"] == {"connectTimeout": "45s"}
    restored_home = tmp_path / "restored"
    archive = tmp_path / "extracted"
    with zipfile.ZipFile(next((node / "dist").glob("*.zip"))) as zf:
        zf.extractall(archive)
    result = run_restore(restored_home, archive)
    assert result.returncode == 0, result.stderr
    config = (restored_home / "config.yml").read_text(encoding="utf-8-sig")
    assert "path: ^/mcp$" in config
    assert "httpHostHeader: internal.example.com" in config
    assert "connectTimeout: 45s" in config


def test_export_refuses_ambiguous_configs_and_accepts_explicit_path(tmp_path):
    node, home, out = make_export_node(tmp_path)
    cfd = home / ".cloudflared"
    for name in ("config.yml", "desksense.yml"):
        (cfd / name).write_text(export_config((cfd / f"{TUNNEL_ID}.json").as_posix()), encoding="utf-8")
    result = run_export(node, home, out)
    assert result.returncode != 0
    assert not list((node / "dist").glob("*.zip"))
    result = run_ps(
        f"$env:USERPROFILE = {ps_quote(home)}\n$env:TEMP = {ps_quote(out)}\n"
        f"& {ps_quote(node / 'scripts' / 'export-move.ps1')} -ConfigPath {ps_quote(cfd / 'desksense.yml')}\nexit $LASTEXITCODE"
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("catch_all", ["http://127.0.0.1:9998", "https://127.0.0.1:9998"])
def test_merge_keeps_http_catch_all_last_and_existing_bytes(tmp_path, catch_all):
    archive, _, home = make_restore_fixtures(tmp_path)
    home.mkdir()
    config = home / "config.yml"
    text = SAME_TUNNEL_CONFIG.replace("http_status:404", catch_all)
    before = b"\xef\xbb\xbf" + ("# Existing comment\r\n" + text.replace("\n", "\r\n")).encode("utf-8")
    config.write_bytes(before)
    result = run_restore(home, archive, merge=True)
    assert result.returncode == 0, result.stderr
    after = config.read_bytes()
    insertion = b"  - hostname: pc.example.com\r\n    service: http://127.0.0.1:18765\r\n"
    assert after.replace(insertion, b"", 1) == before
    assert after.index(b"pc.example.com") < after.index(catch_all.encode())
    cloudflared = shutil.which("cloudflared")
    if cloudflared:
        result = subprocess.run([cloudflared, "tunnel", "--config", str(config), "ingress", "validate"],
                                capture_output=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("invalid", ["missing_catch_all", "duplicate_key", "conflicting_route", "different_defaults"])
def test_merge_refuses_unsafe_config_without_writing_anything(tmp_path, invalid):
    archive, _, home = make_restore_fixtures(tmp_path)
    home.mkdir()
    text = SAME_TUNNEL_CONFIG
    if invalid == "missing_catch_all":
        text = text.replace("  - service: http_status:404\n", "")
    elif invalid == "duplicate_key":
        text += "ingress: []\n"
    elif invalid == "conflicting_route":
        text = text.replace("agy.example.com", "pc.example.com")
    else:
        text = "originRequest:\n  connectTimeout: 45s\n" + text
    config = home / "config.yml"
    before = text.encode("utf-8")
    config.write_bytes(before)
    result = run_restore(home, archive, merge=True)
    assert result.returncode != 0
    assert config.read_bytes() == before
    assert not (home / f"{TUNNEL_ID}.json").exists()
