# Cloudflared Named Tunnel autostart script (Task Scheduler)
# Register:  powershell -ExecutionPolicy Bypass -File scripts/install-tunnel-autostart.ps1
# Idempotent: identifies a running connector by its config path, not a metrics port.
#
# Tunnel name and hostname are read from the cloudflared config.yml by default,
# or supplied explicitly via -TunnelName / -ConfigPath. Nothing user-specific
# is hardcoded in this file.
param(
    [string]$TunnelName,
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'

# Discover the per-user cloudflared home directory dynamically.
$CloudflaredHome = $env:USERPROFILE
if (-not $CloudflaredHome) { $CloudflaredHome = $HOME }
if (-not $CloudflaredHome) { throw 'Unable to determine the current user home directory.' }
$CloudflaredHome = Join-Path $CloudflaredHome '.cloudflared'

# Config path defaults to the standard cloudflared config location.
$Cfg = if ($ConfigPath) { $ConfigPath } else { Join-Path $CloudflaredHome 'config.yml' }

# Discover cloudflared.exe dynamically (system locations, user location, then PATH).
$Cf = $null
foreach ($probe in @(
    (Join-Path $env:ProgramFiles 'cloudflared\cloudflared.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'cloudflared\cloudflared.exe'),
    (Join-Path $CloudflaredHome 'cloudflared.exe')
)) {
    if ($probe -and (Test-Path $probe)) { $Cf = $probe; break }
}
if (-not $Cf) {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { $Cf = $cmd.Source }
}
if (-not $Cf) { throw 'cloudflared.exe not found. Install cloudflared first.' }
if (-not (Test-Path $Cfg)) { throw "config not found: $Cfg" }

# Resolve the tunnel name (and hostname, for reporting) from config.yml when not supplied.
if (-not $TunnelName) {
    $cfgRaw = Get-Content -Raw -Path $Cfg
    if ($cfgRaw -match 'tunnel:\s*(\S+)') { $TunnelName = $Matches[1] }
}
if (-not $TunnelName) { throw "Unable to determine tunnel name. Pass -TunnelName or add a 'tunnel:' line to $Cfg" }

$Log = Join-Path $CloudflaredHome 'tunnel.log'

# The metrics endpoint may use any available port; match the actual config instead.
$Cfg = [System.IO.Path]::GetFullPath($Cfg)
$ConfigArgument = '(?i)(?:^|\s)--config(?:=|\s+)(?:"' + [regex]::Escape($Cfg) + '"|' + [regex]::Escape($Cfg) + ')(?=\s|$)'
$already = @(Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" |
    Where-Object { $_.CommandLine -match $ConfigArgument })
if ($already.Count -gt 0) {
    Write-Host "Cloudflared connector already running for this config (PID $($already.ProcessId -join ', ')); this does not verify tunnel readiness."
    exit 0
}

Start-Process -FilePath $Cf -ArgumentList @('tunnel','--config',('"' + $Cfg + '"'),'run',$TunnelName) `
    -WindowStyle Hidden -RedirectStandardOutput $Log -RedirectStandardError "$Log.err"
Start-Sleep -Seconds 4
Write-Host "Cloudflared named tunnel ($TunnelName) started."
