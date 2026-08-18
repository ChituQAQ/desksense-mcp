"""Side-effect-free checks for the public PowerShell installer contract."""
from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "scripts" / "install.ps1"


def _run_validation_only(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(INSTALLER),
            *arguments,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_named_mode_requires_hostname_and_tunnel_name_pair():
    result = _run_validation_only("-Hostname", "desksense.example.com", "-NoAutostart")
    assert result.returncode != 0
    assert "Hostname and TunnelName must be provided together" in (
        result.stdout + result.stderr
    )


def test_tunnel_name_without_hostname_is_rejected():
    result = _run_validation_only("-TunnelName", "desksense", "-NoAutostart")
    assert result.returncode != 0
    assert "Hostname and TunnelName must be provided together" in (
        result.stdout + result.stderr
    )


def test_port_parameter_rejects_out_of_range_value():
    result = _run_validation_only("-Port", "0", "-NoAutostart")
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "Port" in output
    assert "ParameterArgumentValidationError" in output


def test_local_mode_cloudflared_is_guarded_by_named_mode():
    text = INSTALLER.read_text(encoding="utf-8-sig")
    named_guard = text.index("if ($NamedMode) {", text.index("$Cloudflared = $null"))
    cloudflared_lookup = text.index("Get-Command cloudflared.exe")
    assert named_guard < cloudflared_lookup
    assert "cloudflared.exe is required only for Named Tunnel mode" in text


def test_installer_defaults_and_no_autostart_contract():
    text = INSTALLER.read_text(encoding="utf-8-sig")
    assert "[int]$Port = 8765" in text
    assert "[switch]$NoAutostart" in text
    assert "http://127.0.0.1:$Port" in text
    assert "Start-TemporaryProcess" not in text
    assert "Stop-TemporaryProcess $TemporaryServer" in text
