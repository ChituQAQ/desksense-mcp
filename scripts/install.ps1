[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Hostname,

    [Parameter(Mandatory = $true)]
    [string]$TunnelName,

    [string]$AllowedOrigin
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$LocalOrigin = 'http://127.0.0.1:8765'
$TaskMcp = 'DeskSense MCP'
$TaskTunnel = 'Cloudflared Named Tunnel'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if ($env:OS -ne 'Windows_NT') {
    throw 'DeskSense installation is supported only on Windows.'
}

$Hostname = $Hostname.Trim().ToLowerInvariant()
$TunnelName = $TunnelName.Trim()
if (-not $Hostname) { throw 'A non-empty Hostname is required.' }
if (-not $TunnelName) { throw 'A non-empty TunnelName is required.' }

$PublicOrigin = "https://$Hostname"
$AllowedOrigins = @($PublicOrigin)
if ($AllowedOrigin) {
    $AllowedOrigin = $AllowedOrigin.Trim()
    if ($AllowedOrigins -notcontains $AllowedOrigin) { $AllowedOrigins += $AllowedOrigin }
}
# Origin used for the CORS round-trip verification; always one of the configured origins.
$CorsTestOrigin = if ($AllowedOrigin) { $AllowedOrigin } else { $PublicOrigin }

$Root = Split-Path -Parent $PSScriptRoot
$UserHome = $env:USERPROFILE
if (-not $UserHome) { $UserHome = $HOME }
if (-not $UserHome) { throw 'Unable to determine the current user home directory.' }

$ConfigPath = Join-Path $Root 'config.json'
$SecretsDir = Join-Path $Root '.secrets'
$ApiKeyPath = Join-Path $SecretsDir 'API_KEY.txt'
$DataDir = Join-Path $Root 'data'
$DatabasePath = Join-Path $DataDir 'pc_sense.db'
$LogsDir = Join-Path $Root 'logs'
$VenvDir = Join-Path $Root '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$RequirementsPath = Join-Path $Root 'requirements.txt'
$CloudflaredHome = Join-Path $UserHome '.cloudflared'
$TunnelConfigPath = Join-Path $CloudflaredHome "$TunnelName.yml"

Write-Host 'DeskSense installer' -ForegroundColor Cyan
Write-Host "Project root : $Root"
Write-Host "Hostname     : $Hostname"
Write-Host "Tunnel       : $TunnelName"
if ($AllowedOrigin) { Write-Host "AllowedOrigin: $AllowedOrigin" }

# Discover Python without assuming its installation directory.
$PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
$PythonPrefixArgs = @()
if (-not $PythonCommand) {
    $PythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
    $PythonPrefixArgs = @('-3')
}
if (-not $PythonCommand) {
    throw 'Python 3.11 or newer was not found on PATH.'
}
$PythonExe = $PythonCommand.Source
$VersionText = (& $PythonExe @PythonPrefixArgs -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to run Python.' }
$VersionParts = $VersionText.Split('.')
if ([int]$VersionParts[0] -lt 3 -or ([int]$VersionParts[0] -eq 3 -and [int]$VersionParts[1] -lt 11)) {
    throw "Python 3.11 or newer is required; found $VersionText."
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Host "Creating virtual environment: $VenvDir"
    & $PythonExe @PythonPrefixArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        throw 'Virtual environment creation failed.'
    }
}
Write-Host 'Installing project dependencies...'
if (Test-Path -LiteralPath $RequirementsPath -PathType Leaf) {
    & $VenvPython -m pip install -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
& $VenvPython -m pip install -e $Root
if ($LASTEXITCODE -ne 0) { throw 'Editable project installation failed.' }

# A token already paired with a different node config is presumed to belong to another deployment.
$ExistingConfig = $null
$NodeConfigured = $false
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    try {
        $ExistingConfig = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $ExistingOrigins = @($ExistingConfig.allowed_origins)
        $NodeConfigured = $ExistingOrigins -contains $PublicOrigin
    } catch {
        throw "Existing config is not valid UTF-8 JSON: $ConfigPath"
    }
}
$ApiKeyExists = Test-Path -LiteralPath $ApiKeyPath -PathType Leaf
if ($ApiKeyExists -and -not $NodeConfigured) {
    throw "An existing token is not identified as a deployment for '$Hostname'. Refusing to overwrite or reuse it: $ApiKeyPath"
}
if ((Test-Path -LiteralPath $DatabasePath -PathType Leaf) -and -not $NodeConfigured) {
    throw "An existing database is not identified as a deployment for '$Hostname'. Move it aside before installation: $DatabasePath"
}

New-Item -ItemType Directory -Force -Path $SecretsDir, $DataDir, $LogsDir | Out-Null
if (-not $ApiKeyExists) {
    $RandomBytes = New-Object byte[] 32
    $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Rng.GetBytes($RandomBytes) } finally { $Rng.Dispose() }
    $ApiKey = ([System.BitConverter]::ToString($RandomBytes)).Replace('-', '').ToLowerInvariant()
    [System.IO.File]::WriteAllText($ApiKeyPath, $ApiKey + "`n", $Utf8NoBom)
    Write-Host 'Generated a new bearer token.' -ForegroundColor Green
} else {
    $ExistingKey = ([System.IO.File]::ReadAllText($ApiKeyPath, $Utf8NoBom)).Trim()
    if ($ExistingKey -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Existing token has an unexpected format: $ApiKeyPath"
    }
    Write-Host 'Existing bearer token retained.'
}

if (-not $ExistingConfig) { $ExistingConfig = New-Object PSObject }
function Set-ConfigProperty {
    param([object]$Object, [string]$Name, [object]$Value)
    if ($Object.PSObject.Properties[$Name]) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
    }
}
Set-ConfigProperty $ExistingConfig 'host' '127.0.0.1'
Set-ConfigProperty $ExistingConfig 'port' 8765
Set-ConfigProperty $ExistingConfig 'allowed_origins' $AllowedOrigins
$ConfigJson = $ExistingConfig | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($ConfigPath, $ConfigJson + "`n", $Utf8NoBom)
Write-Host "Wrote config: $ConfigPath"

# Discover cloudflared from PATH and per-user/system locations.
$Cloudflared = $null
$CloudflaredCommand = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
if ($CloudflaredCommand) { $Cloudflared = $CloudflaredCommand.Source }
$CloudflaredCandidates = @(
    (Join-Path $UserHome '.cloudflared\cloudflared.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\cloudflared.exe'),
    (Join-Path $env:ProgramFiles 'cloudflared\cloudflared.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'cloudflared\cloudflared.exe')
)
if (-not $Cloudflared) {
    foreach ($Candidate in $CloudflaredCandidates) {
        if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            $Cloudflared = $Candidate
            break
        }
    }
}
if (-not $Cloudflared) { throw 'cloudflared.exe was not found on PATH or in a standard user/system location.' }
Write-Host "cloudflared : $Cloudflared"
New-Item -ItemType Directory -Force -Path $CloudflaredHome | Out-Null

function ConvertTo-ProcessArgument {
    param([string]$Value)
    if ($Value -notmatch '[\s"]') { return $Value }

    $Escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $Escaped = [regex]::Replace($Escaped, '(\\+)$', '$1$1')
    return '"' + $Escaped + '"'
}

function Invoke-CloudflaredManagement {
    param([string[]]$ArgumentList)

    $StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $StartInfo.FileName = $Cloudflared
    $StartInfo.Arguments = (($ArgumentList | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join ' ')
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true

    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $StartInfo
    try {
        if (-not $Process.Start()) { throw 'cloudflared did not start.' }
        $StandardOutputTask = $Process.StandardOutput.ReadToEndAsync()
        $StandardErrorTask = $Process.StandardError.ReadToEndAsync()
        $Process.WaitForExit()
        return [pscustomobject]@{
            ExitCode = $Process.ExitCode
            StandardOutput = $StandardOutputTask.Result
            StandardError = $StandardErrorTask.Result
        }
    } finally {
        $Process.Dispose()
    }
}

function Read-TunnelList {
    $Command = Invoke-CloudflaredManagement @('tunnel', 'list', '--output', 'json')
    if ($Command.ExitCode -ne 0) {
        return [pscustomobject]@{ Success = $false; Tunnels = @() }
    }
    try {
        $Parsed = ($Command.StandardOutput.Trim() | ConvertFrom-Json)
        return [pscustomobject]@{ Success = $true; Tunnels = @($Parsed) }
    } catch {
        return [pscustomobject]@{ Success = $false; Tunnels = @() }
    }
}

$TunnelListResult = Read-TunnelList
if (-not $TunnelListResult.Success) {
    Write-Host '请完成 Cloudflare 浏览器授权，完成后回来继续。' -ForegroundColor Yellow
    $LoginCommand = Invoke-CloudflaredManagement @('tunnel', 'login')
    if ($LoginCommand.ExitCode -ne 0) { throw 'Cloudflare browser authorization did not complete successfully.' }
    $TunnelListResult = Read-TunnelList
    if (-not $TunnelListResult.Success) { throw 'Cloudflare login could not be validated.' }
}

$MatchingTunnels = @($TunnelListResult.Tunnels | Where-Object { $_.name -eq $TunnelName })
if ($MatchingTunnels.Count -gt 1) { throw "More than one tunnel is named '$TunnelName'." }
if ($MatchingTunnels.Count -eq 0) {
    Write-Host "Creating Named Tunnel: $TunnelName"
    $CreateCommand = Invoke-CloudflaredManagement @('tunnel', 'create', $TunnelName)
    if ($CreateCommand.ExitCode -ne 0) { throw "Failed to create Named Tunnel '$TunnelName'." }
    $TunnelListResult = Read-TunnelList
    if (-not $TunnelListResult.Success) { throw 'Unable to read the tunnel list after creation.' }
    $MatchingTunnels = @($TunnelListResult.Tunnels | Where-Object { $_.name -eq $TunnelName })
    if ($MatchingTunnels.Count -ne 1) { throw 'The newly created tunnel could not be identified uniquely.' }
} else {
    Write-Host "Existing tunnel retained: $TunnelName"
}

$TunnelId = [string]$MatchingTunnels[0].id
if (-not $TunnelId) { throw 'The tunnel has no tunnel ID.' }

$CredentialsPath = Join-Path $CloudflaredHome "$TunnelId.json"
if (-not (Test-Path -LiteralPath $CredentialsPath -PathType Leaf)) {
    throw "Tunnel credentials are missing: $CredentialsPath"
}

Write-Host "Creating/updating DNS route for $Hostname"
$RouteCommand = Invoke-CloudflaredManagement @('tunnel', 'route', 'dns', '--overwrite-dns', $TunnelId, $Hostname)
if ($RouteCommand.ExitCode -ne 0) { throw "Failed to route $Hostname to the tunnel." }

$YamlCredentialsPath = $CredentialsPath.Replace("'", "''")
$TunnelYaml = @"
tunnel: $TunnelId
credentials-file: '$YamlCredentialsPath'
protocol: http2

ingress:
  - hostname: $Hostname
    service: http://127.0.0.1:8765
  - service: http_status:404
"@
[System.IO.File]::WriteAllText($TunnelConfigPath, $TunnelYaml + "`n", $Utf8NoBom)
Write-Host "Wrote tunnel config: $TunnelConfigPath"

foreach ($CommandName in @('Register-ScheduledTask', 'New-ScheduledTaskAction', 'New-ScheduledTaskPrincipal')) {
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "Required ScheduledTasks command is unavailable: $CommandName"
    }
}

$UserId = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited

function Register-InteractiveTask {
    param([string]$Name, [object]$Action, [string]$Description)
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $Settings `
        -Principal $Principal -Description $Description | Out-Null
    Write-Host "Registered user-login task: $Name" -ForegroundColor Green
}

$Wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$McpLauncher = Join-Path $PSScriptRoot 'run-desksense-hidden.vbs'
$TunnelLauncher = Join-Path $PSScriptRoot 'run-cloudflared-hidden.vbs'
if (-not (Test-Path -LiteralPath $Wscript -PathType Leaf)) { throw "wscript.exe was not found: $Wscript" }
if (-not (Test-Path -LiteralPath $McpLauncher -PathType Leaf)) { throw "MCP launcher was not found: $McpLauncher" }
if (-not (Test-Path -LiteralPath $TunnelLauncher -PathType Leaf)) { throw "Tunnel launcher was not found: $TunnelLauncher" }
$McpArguments = "//B //NoLogo `"$McpLauncher`" `"$VenvPython`" `"$Root`""
$TunnelArguments = "//B //NoLogo `"$TunnelLauncher`" `"$Cloudflared`" `"$TunnelConfigPath`" `"$TunnelId`""
$McpAction = New-ScheduledTaskAction -Execute $Wscript -Argument $McpArguments -WorkingDirectory $Root
$TunnelAction = New-ScheduledTaskAction -Execute $Wscript -Argument $TunnelArguments -WorkingDirectory $Root
Register-InteractiveTask $TaskMcp $McpAction 'DeskSense MCP user-login autostart'
Register-InteractiveTask $TaskTunnel $TunnelAction 'Cloudflared Named Tunnel user-login autostart'

$Listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if (-not $Listener) {
    Start-ScheduledTask -TaskName $TaskMcp
    Write-Host 'Started DeskSense MCP task.'
} else {
    Write-Host "Port 8765 is already listening (PID $($Listener[0].OwningProcess)); not starting a duplicate server."
}

$MatchingConnectors = @(Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine.Contains($TunnelConfigPath) -or $_.CommandLine.Contains($TunnelId)) })
if ($MatchingConnectors.Count -eq 0) {
    Start-ScheduledTask -TaskName $TaskTunnel
    Write-Host 'Started the cloudflared task.'
} elseif ($MatchingConnectors.Count -eq 1) {
    Write-Host 'The cloudflared connector is already running; not starting a duplicate.'
} else {
    throw 'Multiple cloudflared connector processes are running.'
}

# The verifier reads the token file itself and never prints the token. Local requests ignore proxy environment variables.
$VerifierPath = Join-Path $env:TEMP ("desksense-verify-{0}.py" -f ([Guid]::NewGuid().ToString('N')))
$Verifier = @'
import asyncio
import sys
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

EXPECTED = {
    "pc_get_context", "pc_get_focus", "pc_list_open_apps", "pc_get_idle_status",
    "pc_get_pc_status", "pc_get_top_processes", "pc_get_recent_focus",
}

async def verify_http(base, token, origin, local):
    timeout = httpx2.Timeout(20.0)
    async with httpx2.AsyncClient(timeout=timeout, trust_env=not local) as client:
        health = await client.get(base + "/healthz")
        assert health.status_code == 200, (base, "healthz", health.status_code)
        unauthorized = await client.post(
            base + "/mcp",
            headers={"Origin": origin, "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert unauthorized.status_code == 401, (base, "unauthorized", unauthorized.status_code)
        assert unauthorized.headers.get("access-control-allow-origin") == origin
        exposed = unauthorized.headers.get("access-control-expose-headers", "").lower()
        assert "mcp-session-id" in exposed, (base, "expose headers", exposed)
        preflight = await client.options(
            base + "/mcp",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type,mcp-protocol-version",
            },
        )
        assert preflight.status_code == 200, (base, "preflight", preflight.status_code)
        assert preflight.headers.get("access-control-allow-origin") == origin

    headers = {
        "Authorization": "Bearer " + token,
        "Origin": origin,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx2.AsyncClient(headers=headers, timeout=timeout, trust_env=not local) as client:
        async with streamable_http_client(base + "/mcp", http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert names == EXPECTED, (base, "tools", sorted(names))
                context = await session.call_tool("pc_get_context", {})
                assert context.content and not context.is_error, (base, "pc_get_context")

async def main():
    token = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
    origin = sys.argv[2]
    public_base = sys.argv[3]
    last_error = None
    for _ in range(30):
        try:
            await verify_http("http://127.0.0.1:8765", token, origin, True)
            break
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)
    else:
        raise last_error
    last_error = None
    for _ in range(30):
        try:
            await verify_http(public_base, token, origin, False)
            print("Local/public MCP and CORS verification passed (7 tools).")
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(3)
    raise last_error

asyncio.run(main())
'@
[System.IO.File]::WriteAllText($VerifierPath, $Verifier, $Utf8NoBom)
try {
    & $VenvPython $VerifierPath $ApiKeyPath $CorsTestOrigin $PublicOrigin
    if ($LASTEXITCODE -ne 0) { throw 'Local/public verification failed.' }
} finally {
    if (Test-Path -LiteralPath $VerifierPath) { [System.IO.File]::Delete($VerifierPath) }
}

Write-Host ''
Write-Host 'DeskSense installation complete.' -ForegroundColor Green
Write-Host "MCP URL    : $PublicOrigin/mcp"
Write-Host "Token file : $ApiKeyPath"
