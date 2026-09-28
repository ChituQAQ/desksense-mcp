"""Windows launcher/ACL regressions using isolated files and mocked processes."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-only scripts")


def ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_ps(script: str) -> subprocess.CompletedProcess[str]:
    # A missing mock must fail immediately, not inspect/control the developer's PC.
    guards = "\n".join(
        f"function {name} {{ [Console]::Error.WriteLine('Unmocked {name}'); "
        "[Environment]::Exit(97) }"
        for name in (
            "Invoke-RestMethod", "Get-NetTCPConnection", "Get-CimInstance",
            "Get-Process", "Start-Process", "Stop-Process", "Wait-Process",
        )
    )
    command = "[Console]::OutputEncoding = [Text.UTF8Encoding]::new();\n" + guards + "\n" + script
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    # A parent pwsh session can leak incompatible PS7 modules into Windows PS5.1.
    env = {k: v for k, v in os.environ.items() if k.lower() != "psmodulepath"}
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        env=env,
    )


@pytest.fixture
def launcher_root(tmp_path):
    root = tmp_path / "node with spaces"
    (root / "scripts").mkdir(parents=True)
    for name in ("start.ps1", "stop.ps1"):
        shutil.copy2(SCRIPTS / name, root / "scripts" / name)
    (root / "config.json").write_text('{"port": 18765}', encoding="utf-8")
    return root


def launch(root, setup, wait=False, extra_args=""):
    return run_ps(
        f"$FakePython = {ps_quote(root / '.venv' / 'Scripts' / 'python.exe')};\n"
        # The launcher's native taskkill path must not resolve on mock failures.
        + f"$env:WINDIR = {ps_quote(root / 'blocked-native-tools')};\n"
        + setup
        + f"\n& {ps_quote(root / 'scripts' / 'start.ps1')}"
        + (f" {extra_args}" if extra_args else "")
        + (" -Wait" if wait else "")
        + "; exit $LASTEXITCODE"
    )


LISTENER = """
function Get-NetTCPConnection { [pscustomobject]@{ OwningProcess = 12345 } }
function Get-CimInstance {
    [pscustomobject]@{ CommandLine = '"' + $FakePython + '" -m desksense.server' }
}
"""


def test_foreign_listener_is_not_reported_as_desksense(launcher_root):
    result = launch(launcher_root, """
function Get-NetTCPConnection { [pscustomobject]@{ OwningProcess = 12345 } }
function Get-CimInstance { [pscustomobject]@{ CommandLine = 'python main.py serve' } }
function Start-Process { throw 'Unexpected start' }
function Invoke-RestMethod { throw 'Unexpected HTTP request' }
""")
    assert result.returncode == 1
    log = (launcher_root / "logs" / "startup.log").read_text(encoding="utf-8-sig")
    assert "occupied by a different process" in log
    assert "Unexpected" not in log


def test_matching_process_still_requires_healthy_response(launcher_root):
    result = launch(launcher_root, LISTENER + """
function Invoke-RestMethod { @{ ok = $true; service = 'Another Service' } }
""")
    assert result.returncode == 1
    assert "did not return a DeskSense health response" in result.stderr


def test_healthy_existing_server_is_reused(launcher_root):
    result = launch(launcher_root, LISTENER + """
function Invoke-RestMethod { @{ ok = $true; service = 'DeskSense MCP' } }
function Start-Process { throw 'Unexpected start' }
""")
    assert result.returncode == 0, result.stderr
    assert "already healthy on port 18765" in result.stdout


def test_existing_server_death_is_retried_in_task(launcher_root):
    result = launch(launcher_root, LISTENER + """
function Invoke-RestMethod { @{ ok = $true; service = 'DeskSense MCP' } }
function Wait-Process { }
""", wait=True, extra_args="-MaxRetries 1 -RetryDelaySeconds 1")
    assert result.returncode == 1
    assert "already healthy on port 18765" in result.stdout
    log = (launcher_root / "logs" / "startup.log").read_text(encoding="utf-8-sig")
    assert "The existing DeskSense process exited." in log
    assert "Retrying in 1 seconds (0 retries left)." in log
    assert "Giving up after exhausting retries" in log


def test_empty_listener_without_venv_is_a_failure(launcher_root):
    result = launch(launcher_root, "function Get-NetTCPConnection { }")
    assert result.returncode == 1
    assert "Venv Python was not found" in result.stderr


@pytest.mark.parametrize(("real_child", "child_exit", "expected_exit"), [
    (False, 7, 7), (True, 7, 7), (True, -1, 1),
])
def test_wait_preserves_server_exit_code_and_previous_stderr(
    launcher_root, real_child, child_exit, expected_exit,
):
    python = launcher_root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()  # Never executed: Start-Process is mocked below.
    logs = launcher_root / "logs"
    logs.mkdir()
    (logs / "stderr.log").write_text("previous failure", encoding="utf-8")
    result = launch(launcher_root, (
        f"$UseRealChild = {'$true' if real_child else '$false'}; $ChildExitCode = {child_exit};\n"
    ) + LISTENER + r"""
$global:ListenerCalls = 0
function Get-NetTCPConnection {
    $global:ListenerCalls++
    if ($global:ListenerCalls -gt 1) { [pscustomobject]@{ OwningProcess = 12345 } }
}
function Invoke-RestMethod { @{ ok = $true; service = 'DeskSense MCP' } }
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle,
          [switch]$PassThru, $RedirectStandardOutput, $RedirectStandardError)
    if ($UseRealChild) {
        $code = 'Start-Sleep -Milliseconds 800; [Console]::Error.WriteLine("new stderr"); exit ' + $ChildExitCode
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
        return Microsoft.PowerShell.Management\Start-Process -FilePath "$PSHOME\powershell.exe" `
            -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', $encoded) `
            -PassThru -WindowStyle Hidden -RedirectStandardOutput $RedirectStandardOutput `
            -RedirectStandardError $RedirectStandardError
    }
    Set-Content -LiteralPath $RedirectStandardError -Value 'new stderr'
    $p = [pscustomobject]@{ HasExited = $false; ExitCode = 7; Id = 12345; Handle = 1 }
    $p | Add-Member ScriptMethod Refresh { }
    $p | Add-Member ScriptMethod WaitForExit { $this.HasExited = $true }
    $p | Add-Member ScriptMethod Dispose { }
    return $p
}
""", wait=True, extra_args="-MaxRetries 0")
    assert result.returncode == expected_exit, result.stderr
    assert (logs / "stderr.log.previous").read_text() == "previous failure"
    # A redirected powershell child appends a CLIXML footer containing
    # ANSI-codepage text; decode tolerantly and assert on the ASCII message.
    assert "new stderr" in (logs / "stderr.log").read_text(encoding="utf-8", errors="replace")
    assert f"Server exited with code {child_exit}" in (logs / "startup.log").read_text(encoding="utf-8-sig")


def test_launcher_retries_after_server_death(launcher_root):
    python = launcher_root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()  # Never executed: Start-Process is mocked below.
    result = launch(launcher_root, LISTENER + r"""
$global:ListenerCalls = 0
$global:StartCalls = 0
function Get-NetTCPConnection {
    $global:ListenerCalls++
    if ($global:ListenerCalls -in @(2, 4)) { [pscustomobject]@{ OwningProcess = 12345 } }
}
function Invoke-RestMethod { @{ ok = $true; service = 'DeskSense MCP' } }
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle,
          [switch]$PassThru, $RedirectStandardOutput, $RedirectStandardError)
    $global:StartCalls++
    $exit = 7
    if ($global:StartCalls -ge 2) { $exit = 0 }
    $p = [pscustomobject]@{ HasExited = $false; ExitCode = $exit; Id = 12345; Handle = 1 }
    $p | Add-Member ScriptMethod Refresh { }
    $p | Add-Member ScriptMethod WaitForExit { $this.HasExited = $true }
    $p | Add-Member ScriptMethod Dispose { }
    return $p
}
""", wait=True, extra_args="-MaxRetries 1 -RetryDelaySeconds 1")
    assert result.returncode == 0, result.stderr
    log = (launcher_root / "logs" / "startup.log").read_text(encoding="utf-8-sig")
    assert "Server exited with code 7." in log
    assert "Retrying in 1 seconds (0 retries left)." in log
    assert "Server exited with code 0." in log


@pytest.mark.parametrize("before_ready", [False, True])
def test_retry_keeps_last_attempt_output(launcher_root, before_ready):
    python = launcher_root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    logs = launcher_root / "logs"
    logs.mkdir()
    (logs / "stderr.log").write_text("older session", encoding="utf-8")
    result = launch(launcher_root, (
        f"$BeforeReady = {'$true' if before_ready else '$false'};\n"
    ) + LISTENER + r"""
$global:Child = $null
$global:Attempt = 0
function Get-NetTCPConnection {
    if ($global:Child -and -not $global:Child.HasExited) {
        if ($BeforeReady -and $global:Attempt -eq 1) {
            $global:Child.WaitForExit()
        } else {
            [pscustomobject]@{ OwningProcess = 12345 }
        }
    }
}
function Invoke-RestMethod { @{ ok = $true; service = 'DeskSense MCP' } }
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle,
          [switch]$PassThru, $RedirectStandardOutput, $RedirectStandardError)
    $global:Attempt++
    $exit = if ($global:Attempt -eq 1) { 7 } else { 0 }
    $code = 'Start-Sleep -Milliseconds 1000; [Console]::Out.WriteLine("OUT_ATTEMPT_' + $global:Attempt + '"); [Console]::Error.WriteLine("ERR_ATTEMPT_' + $global:Attempt + '"); exit ' + $exit
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
    $global:Child = Microsoft.PowerShell.Management\Start-Process -FilePath "$PSHOME\powershell.exe" `
        -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', $encoded) `
        -PassThru -WindowStyle Hidden -RedirectStandardOutput $RedirectStandardOutput `
        -RedirectStandardError $RedirectStandardError
    return $global:Child
}
""", wait=True, extra_args="-MaxRetries 1 -RetryDelaySeconds 1")
    assert result.returncode == 0, result.stderr
    for name, marker in (("stdout", "OUT"), ("stderr", "ERR")):
        previous = (logs / f"{name}.log.previous").read_text(encoding="utf-8-sig", errors="replace")
        current = (logs / f"{name}.log").read_text(encoding="utf-8-sig", errors="replace")
        assert f"{marker}_ATTEMPT_1" in previous
        assert f"{marker}_ATTEMPT_2" in current
        assert f"{marker}_ATTEMPT_1" not in current


def test_missing_http_mock_fails_without_contacting_real_service(launcher_root):
    result = launch(launcher_root, LISTENER)
    assert result.returncode == 97
    assert "Unmocked Invoke-RestMethod" in result.stderr


@pytest.mark.parametrize("server_present", [False, True])
def test_stop_ends_only_this_launcher_then_its_server(launcher_root, server_present):
    script = (
        f"$Node = {ps_quote(launcher_root)};\n"
        f"$ServerPresent = {'$true' if server_present else '$false'};\n"
    ) + r"""
$ErrorActionPreference = 'Stop'
$global:Stopped = @()
$global:Processes = @(
    [pscustomobject]@{ ProcessId = 101; Name = 'powershell.exe'; CommandLine = 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $Node + '\scripts\start.ps1" -Wait' },
    [pscustomobject]@{ ProcessId = 201; Name = 'powershell.exe'; CommandLine = 'powershell.exe -File "' + $Node + '-other\scripts\start.ps1" -Wait' },
    [pscustomobject]@{ ProcessId = 202; Name = 'powershell.exe'; CommandLine = 'powershell.exe -Command Write-Output '' -File "' + $Node + '\scripts\start.ps1" -Wait''' },
    [pscustomobject]@{ ProcessId = 203; Name = 'python.exe'; CommandLine = '"' + $Node + '-other\.venv\Scripts\python.exe" -m desksense.server' }
)
if ($ServerPresent) {
    $global:Processes += [pscustomobject]@{ ProcessId = 102; Name = 'python.exe'; CommandLine = '"' + $Node + '\.venv\Scripts\python.exe" -m desksense.server' }
}
function Get-CimInstance {
    param($ClassName, $Filter)
    $items = @($global:Processes | Where-Object { $global:Stopped -notcontains $_.ProcessId })
    if ($Filter -match '^ProcessId = (\d+)$') { return $items | Where-Object { $_.ProcessId -eq [int]$Matches[1] } }
    return $items
}
function Get-Process {
    param($Id)
    if ($Id -notin @(101, 102)) { throw 'Foreign process accessed' }
    $p = [pscustomobject]@{ Id = $Id; Handle = 1; HasExited = $false }
    $p | Add-Member ScriptMethod WaitForExit { param($Timeout); return $this.HasExited }
    $p | Add-Member ScriptMethod Dispose { }
    return $p
}
function Stop-Process {
    param($InputObject, [switch]$Force)
    if ($InputObject.Id -notin @(101, 102)) { throw 'Foreign process stopped' }
    $global:Stopped += $InputObject.Id
    $InputObject.HasExited = $true
}
""" + f"\n& {ps_quote(launcher_root / 'scripts' / 'stop.ps1')}\n" + r"""
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output ('STOPPED_IDS=' + ($global:Stopped -join ','))
"""
    result = run_ps(script)
    assert result.returncode == 0, result.stderr
    expected = "101,102" if server_present else "101"
    assert f"STOPPED_IDS={expected}" in result.stdout


def test_acl_removes_broad_grants_and_protects_new_files(tmp_path):
    root = tmp_path / "private node"
    (root / ".secrets").mkdir(parents=True)
    (root / "data" / "nested").mkdir(parents=True)
    token = root / ".secrets" / "API_KEY.txt"
    token.write_text("fake-test-token", encoding="ascii")
    (root / "data" / "nested" / "history.db").touch()
    result = run_ps(f"""
$ErrorActionPreference = 'Stop'
$root = {ps_quote(root)}
$token = {ps_quote(token)}
$a = Get-Acl -LiteralPath $token
$sid = New-Object System.Security.Principal.SecurityIdentifier('S-1-1-0')
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')
$a.AddAccessRule($rule)
Set-Acl -LiteralPath $token -AclObject $a
& {ps_quote(SCRIPTS / 'protect-private-data.ps1')} -Root $root | Out-Null
& {ps_quote(SCRIPTS / 'protect-private-data.ps1')} -Root $root | Out-Null
Set-Content -LiteralPath (Join-Path $root '.secrets\\new-token.txt') -Value 'fake'
Set-Content -LiteralPath (Join-Path $root 'data\\new.db') -Value 'fake'
$allowed = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18', 'S-1-5-32-544')
$items = @(Get-Item -Force (Join-Path $root '.secrets'), (Join-Path $root 'data'))
$items += @(Get-ChildItem -LiteralPath (Join-Path $root '.secrets'), (Join-Path $root 'data') -Force -Recurse)
foreach ($item in $items) {{
    $acl = Get-Acl -LiteralPath $item.FullName
    $rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if ($rules.Count -ne 3) {{ throw "Unexpected rules on $($item.Name)" }}
    foreach ($r in $rules) {{
        if ($allowed -notcontains $r.IdentityReference.Value -or $r.AccessControlType -ne 'Allow') {{
            throw 'Unexpected access grant'
        }}
    }}
}}
Write-Output 'ACL_OK'
""")
    assert result.returncode == 0, result.stderr
    assert "ACL_OK" in result.stdout
    assert token.read_text() == "fake-test-token"


@pytest.mark.parametrize("at_root", [False, True])
def test_acl_rejects_junction_before_changing_permissions(tmp_path, at_root):
    actual = tmp_path / "actual"
    (actual / ".secrets").mkdir(parents=True)
    (actual / "data").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "redirected" if at_root else actual / "data" / "redirected"
    target = actual if at_root else outside
    root = link if at_root else actual
    try:
        result = run_ps(f"""
$ErrorActionPreference = 'Stop'
New-Item -ItemType Junction -Path {ps_quote(link)} -Target {ps_quote(target)} | Out-Null
$before = (Get-Acl -LiteralPath {ps_quote(actual / '.secrets')}).Sddl
$outsideBefore = (Get-Acl -LiteralPath {ps_quote(outside)}).Sddl
try {{
    & {ps_quote(SCRIPTS / 'protect-private-data.ps1')} -Root {ps_quote(root)}
    throw 'Unexpected success'
}} catch {{
    if ($_.Exception.Message -notmatch 'reparse point') {{ throw }}
}}
if ($before -ne (Get-Acl -LiteralPath {ps_quote(actual / '.secrets')}).Sddl) {{ throw 'Partial ACL mutation' }}
if ($outsideBefore -ne (Get-Acl -LiteralPath {ps_quote(outside)}).Sddl) {{ throw 'Outside ACL mutation' }}
Write-Output 'REPARSE_REJECTED'
""")
        assert result.returncode == 0, result.stderr
        assert "REPARSE_REJECTED" in result.stdout
    finally:
        if link.exists():
            os.rmdir(link)


def test_installers_use_retry_without_unregistering_existing_task():
    for name in ("install.ps1", "install-autostart.ps1"):
        text = (SCRIPTS / name).read_text(encoding="utf-8-sig")
        assert "-RestartCount 3" in text
        assert "-RestartInterval (New-TimeSpan -Minutes 1)" in text
        assert "-StartWhenAvailable" in text
        assert "Unregister-ScheduledTask" not in text
        assert "-LogonType Interactive" in text
        assert "-RunLevel Limited" in text
    text = (SCRIPTS / "install.ps1").read_text(encoding="utf-8-sig")
    assert text.index("'protect-private-data.ps1'") < text.index("$BootstrapArgs =")
    vbs = (SCRIPTS / "run-desksense-hidden.vbs").read_text(encoding="utf-8-sig")
    assert "start.ps1" in vbs and ' -Wait"' in vbs
    assert "shell.Run(command, 0, True)" in vbs
    assert "WScript.Quit exitCode" in vbs
    launcher = (SCRIPTS / "start.ps1").read_text(encoding="utf-8-sig")
    assert "$MaxRetries" in launcher and "$RetryDelaySeconds" in launcher
    assert "Retrying in" in launcher and "Giving up after exhausting retries" in launcher


def test_tunnel_reuses_matching_connector_without_metrics_port(tmp_path):
    config = tmp_path / "config with spaces.yml"
    config.write_text("tunnel: test-only\ningress:\n  - service: http_status:404\n")
    result = run_ps(f"""
function Get-CimInstance {{
    [pscustomobject]@{{ ProcessId = 12345; CommandLine = 'cloudflared.exe tunnel --config "' + {ps_quote(config)} + '" run test-only' }}
}}
function Get-NetTCPConnection {{ throw 'Must not probe a fixed metrics port' }}
function Start-Process {{ throw 'Must not start a duplicate connector' }}
function Get-Command {{ [pscustomobject]@{{ Source = 'cloudflared.exe' }} }}
& {ps_quote(SCRIPTS / 'start-named-tunnel.ps1')} -ConfigPath {ps_quote(config)}
""")
    assert result.returncode == 0, result.stderr
    assert "connector already running" in result.stdout
