"""MOVE 迁移脚本契约测试：临时目录内完成，不触碰真实 ~/.cloudflared。"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-only scripts")

TUNNEL_ID = "11111111-2222-3333-4444-555555555555"
OTHER_TUNNEL_ID = "99999999-8888-7777-6666-555555555555"
ROUTES = [("pc.example.com", "http://127.0.0.1:18765")]


def ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_ps(script: str) -> subprocess.CompletedProcess[str]:
    command = "[Console]::OutputEncoding = [Text.UTF8Encoding]::new();\n" + script
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    # A parent pwsh session can leak incompatible PS7 modules into Windows PS5.1.
    env = {k: v for k, v in os.environ.items() if k.lower() != "psmodulepath"}
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        env=env,
    )


def credential_json(tunnel_id: str) -> str:
    return json.dumps({"AccountTag": "a", "TunnelSecret": "s", "TunnelID": tunnel_id})


def write_manifest(archive: Path, *, tunnel_id: str = TUNNEL_ID,
                   routes=ROUTES, cred_name: str | None = None,
                   include_routes: bool = True) -> None:
    manifest = {
        "tunnel_id": tunnel_id,
        "credentials_file": cred_name or f"{tunnel_id}.json",
        "hostname": routes[0][0] if routes else "",
        "export_time": "2026-09-28T00:00:00+08:00",
    }
    if include_routes and routes is not None:
        manifest["routes"] = [{"hostname": h, "service": s} for h, s in routes]
    (archive / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def make_restore_fixtures(tmp_path: Path, *, cred_tunnel_id: str = TUNNEL_ID,
                          routes=ROUTES, include_routes=True, legacy_cfg=False):
    archive = tmp_path / "archive"
    cfd_archive = archive / "cloudflared"
    cfd_archive.mkdir(parents=True)
    (cfd_archive / f"{TUNNEL_ID}.json").write_text(credential_json(cred_tunnel_id), encoding="ascii")
    if legacy_cfg:
        (cfd_archive / "config.yml").write_text(
            f"tunnel: {TUNNEL_ID}\ncredentials-file: old.json\nprotocol: http2\n\n"
            "ingress:\n  - hostname: legacy.example.com\n    service: http://127.0.0.1:8765\n"
            "  - service: http_status:404\n",
            encoding="utf-8",
        )
    write_manifest(archive, routes=routes, include_routes=include_routes)
    home = tmp_path / "cfdhome"
    return archive, cfd_archive, home


def run_restore(cfd_home: Path, archive: Path, *, merge: bool = False) -> subprocess.CompletedProcess[str]:
    flag = " -MergeIngress" if merge else ""
    return run_ps(
        f"& {ps_quote(SCRIPTS / 'restore-tunnel-config.ps1')} "
        f"-ManifestFile {ps_quote(archive / 'manifest.json')} "
        f"-ArchiveCfdDir {ps_quote(archive / 'cloudflared')} "
        f"-CfdHome {ps_quote(cfd_home)}{flag}\nexit $LASTEXITCODE"
    )


SHARED_CONFIG = (
    f"tunnel: {OTHER_TUNNEL_ID}\n"
    "credentials-file: C:\\old\\.cloudflared\\other.json\n"
    "protocol: http2\n\n"
    "ingress:\n"
    "  - hostname: agy.example.com\n"
    "    service: http://127.0.0.1:9999\n"
    "  - service: http_status:404\n"
)

SAME_TUNNEL_CONFIG = (
    f"tunnel: {TUNNEL_ID}\n"
    "credentials-file: C:\\old\\.cloudflared\\self.json\n"
    "protocol: http2\n\n"
    "ingress:\n"
    "  - hostname: agy.example.com\n"
    "    service: http://127.0.0.1:9999\n"
    "  - service: http_status:404\n"
)


# ---------------------------------------------------------------------------
# export-move.ps1
# ---------------------------------------------------------------------------

def make_export_node(tmp_path: Path) -> tuple[Path, Path, Path]:
    node = tmp_path / "node"
    (node / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPTS / "export-move.ps1", node / "scripts" / "export-move.ps1")
    (node / "config.json").write_text('{"port": 18765}', encoding="utf-8")
    home = tmp_path / "home"
    cfd = home / ".cloudflared"
    cfd.mkdir(parents=True)
    (cfd / f"{TUNNEL_ID}.json").write_text(credential_json(TUNNEL_ID), encoding="ascii")
    (cfd / f"{OTHER_TUNNEL_ID}.json").write_text(credential_json(OTHER_TUNNEL_ID), encoding="ascii")
    out = tmp_path / "out"
    out.mkdir()
    return node, home, out


def run_export(node: Path, home: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return run_ps(
        f"$env:USERPROFILE = {ps_quote(home)}\n"
        f"$env:TEMP = {ps_quote(out)}\n"
        f"& {ps_quote(node / 'scripts' / 'export-move.ps1')}\nexit $LASTEXITCODE"
    )


def test_export_packs_only_referenced_credential_and_local_routes(tmp_path):
    node, home, out = make_export_node(tmp_path)
    (home / ".cloudflared" / "config.yml").write_text(
        f"tunnel: {TUNNEL_ID}\n"
        f'credentials-file: "{home / ".cloudflared" / (TUNNEL_ID + ".json")}"\n'
        "protocol: http2\n\n"
        "ingress:\n"
        "  - hostname: pc.example.com\n"
        "    service: http://127.0.0.1:18765\n"
        "  - hostname: other.example.com\n"
        "    service: http://127.0.0.1:9999\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )

    result = run_export(node, home, out)

    assert result.returncode == 0, result.stderr
    zips = list((node / "dist").glob("desksense-move-*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        names = zf.namelist()
        assert f"cloudflared/{TUNNEL_ID}.json" in names
        assert f"cloudflared/{OTHER_TUNNEL_ID}.json" not in names
        assert "cloudflared/config.yml" not in names
        manifest = json.loads(zf.read("manifest.json").decode("utf-8-sig"))
    assert manifest["tunnel_id"] == TUNNEL_ID
    assert manifest["credentials_file"] == f"{TUNNEL_ID}.json"
    assert manifest["hostname"] == "pc.example.com"
    assert manifest["routes"] == [
        {"hostname": "pc.example.com", "service": "http://127.0.0.1:18765"}
    ]


def test_export_refuses_when_no_route_targets_local_port(tmp_path):
    node, home, out = make_export_node(tmp_path)
    (home / ".cloudflared" / "config.yml").write_text(
        f"tunnel: {TUNNEL_ID}\n"
        f'credentials-file: "{home / ".cloudflared" / (TUNNEL_ID + ".json")}"\n'
        "ingress:\n"
        "  - hostname: other.example.com\n"
        "    service: http://127.0.0.1:9999\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )

    result = run_export(node, home, out)

    assert result.returncode == 1
    assert "no ingress route" in result.stdout
    assert not list((node / "dist").glob("*.zip"))


def test_export_refuses_when_credential_tunnelid_mismatches(tmp_path):
    node, home, out = make_export_node(tmp_path)
    # config.yml 声明 TUNNEL_ID，但引用的凭据文件属于另一条隧道。
    (home / ".cloudflared" / "config.yml").write_text(
        f"tunnel: {TUNNEL_ID}\n"
        f'credentials-file: "{home / ".cloudflared" / (OTHER_TUNNEL_ID + ".json")}"\n'
        "ingress:\n"
        "  - hostname: pc.example.com\n"
        "    service: http://127.0.0.1:18765\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )

    result = run_export(node, home, out)

    assert result.returncode == 1
    assert "does not match" in result.stdout
    assert not list((node / "dist").glob("*.zip"))


# ---------------------------------------------------------------------------
# restore-tunnel-config.ps1
# ---------------------------------------------------------------------------

def test_restore_writes_fresh_config_from_manifest(tmp_path):
    archive, cfd_archive, home = make_restore_fixtures(tmp_path)

    result = run_restore(home, archive)

    assert result.returncode == 0, result.stderr
    assert (home / f"{TUNNEL_ID}.json").exists()
    cfg = (home / "config.yml").read_text(encoding="utf-8-sig")
    assert f"tunnel: {TUNNEL_ID}" in cfg
    assert f"credentials-file: {home / (TUNNEL_ID + '.json')}" in cfg
    assert "  - hostname: pc.example.com" in cfg
    assert "    service: http://127.0.0.1:18765" in cfg
    assert "  - service: http_status:404" in cfg


def test_restore_verifies_credential_tunnelid(tmp_path):
    archive, cfd_archive, home = make_restore_fixtures(tmp_path, cred_tunnel_id=OTHER_TUNNEL_ID)

    result = run_restore(home, archive)

    assert result.returncode == 1
    assert "does not match" in result.stderr
    assert not home.exists() or not list(home.iterdir())


def test_restore_refuses_existing_config_of_other_tunnel_even_with_merge(tmp_path):
    archive, cfd_archive, home = make_restore_fixtures(tmp_path)
    home.mkdir()
    (home / "config.yml").write_text(SHARED_CONFIG, encoding="utf-8")
    before = (home / "config.yml").read_bytes()

    result = run_restore(home, archive, merge=True)

    assert result.returncode == 1
    assert "exactly one tunnel" in result.stderr
    assert (home / "config.yml").read_bytes() == before
    assert not (home / f"{TUNNEL_ID}.json").exists()


def test_restore_same_tunnel_requires_explicit_merge(tmp_path):
    archive, cfd_archive, home = make_restore_fixtures(tmp_path)
    home.mkdir()
    (home / "config.yml").write_text(SAME_TUNNEL_CONFIG, encoding="utf-8")
    before = (home / "config.yml").read_bytes()

    result = run_restore(home, archive)

    assert result.returncode == 1
    assert "-MergeIngress" in result.stderr
    assert (home / "config.yml").read_bytes() == before
    assert not (home / f"{TUNNEL_ID}.json").exists()


def test_restore_merge_appends_missing_routes_before_catch_all(tmp_path):
    archive, cfd_archive, home = make_restore_fixtures(
        tmp_path, routes=ROUTES + [("agy.example.com", "http://127.0.0.1:9999")]
    )
    home.mkdir()
    (home / "config.yml").write_text(SAME_TUNNEL_CONFIG, encoding="utf-8")

    result = run_restore(home, archive, merge=True)

    assert result.returncode == 0, result.stderr
    cfg = (home / "config.yml").read_text(encoding="utf-8-sig")
    expected = (
        f"tunnel: {TUNNEL_ID}\n"
        "credentials-file: C:\\old\\.cloudflared\\self.json\n"
        "protocol: http2\n\n"
        "ingress:\n"
        "  - hostname: agy.example.com\n"
        "    service: http://127.0.0.1:9999\n"
        "  - hostname: pc.example.com\n"
        "    service: http://127.0.0.1:18765\n"
        "  - service: http_status:404\n"
    )
    assert cfg == expected

    second = run_restore(home, archive, merge=True)
    assert second.returncode == 0, second.stderr
    assert "nothing to merge" in second.stdout
    assert (home / "config.yml").read_text(encoding="utf-8-sig") == expected


def test_restore_legacy_archive_falls_back_to_first_route(tmp_path):
    archive, cfd_archive, home = make_restore_fixtures(tmp_path, include_routes=False, legacy_cfg=True)

    result = run_restore(home, archive)

    assert result.returncode == 0, result.stderr
    assert "Falling back" in result.stdout
    cfg = (home / "config.yml").read_text(encoding="utf-8-sig")
    assert "  - hostname: legacy.example.com" in cfg
    assert "    service: http://127.0.0.1:8765" in cfg
    assert "  - service: http_status:404" in cfg


def test_restore_legacy_without_archived_config_is_a_failure(tmp_path):
    archive, cfd_archive, home = make_restore_fixtures(tmp_path, include_routes=False)

    result = run_restore(home, archive)

    assert result.returncode == 1
    assert "re-export" in result.stderr


# ---------------------------------------------------------------------------
# 脚本间契约
# ---------------------------------------------------------------------------

def test_move_script_text_contracts():
    install_move = (SCRIPTS / "install-move.ps1").read_text(encoding="utf-8-sig")
    assert "restore-tunnel-config.ps1" in install_move
    assert "install-autostart.ps1" in install_move
    assert "start.ps1" in install_move
    assert "install-tunnel-autostart.ps1" in install_move
    assert "-MergeIngress" in install_move
    assert "Unregister-ScheduledTask" not in install_move

    export_move = (SCRIPTS / "export-move.ps1").read_text(encoding="utf-8-sig")
    # 绝不重新引入“打包目录下所有 JSON”的行为。
    assert "-like '*.json'" not in export_move
    assert "credentials-file" in export_move
    assert "ConvertTo-Json -Depth 4" in export_move

    tunnel_autostart = (SCRIPTS / "install-tunnel-autostart.ps1").read_text(encoding="utf-8-sig")
    assert "Unregister-ScheduledTask" not in tunnel_autostart
    assert "-RestartCount 3" in tunnel_autostart
    assert "-Force" in tunnel_autostart
