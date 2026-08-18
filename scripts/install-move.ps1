# DeskSense MOVE — 迁移安装 (在新电脑解压目录中运行)
# 用法: 解压 desksense-move-<ts>.zip 后，在解压出的项目根目录运行:
#        .\scripts\install-move.ps1
# 本脚本推导项目根目录、动态发现环境，不硬编码项目路径或用户目录。
$ErrorActionPreference = 'Stop'

# ---- 1. 推导解压目录与项目根目录（archive root -> project -> scripts） ----
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ExtractionRoot = Split-Path -Parent $ProjectRoot
$HomeDir = $env:USERPROFILE
if (-not $HomeDir) { $HomeDir = Join-Path $env:HOMEDRIVE $env:HOMEPATH }
$CfdHome = Join-Path $HomeDir '.cloudflared'
$LocalOrigin = 'http://127.0.0.1:8765'

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "DeskSense MOVE — install"
Write-Host "Extract root : $ExtractionRoot"
Write-Host "Project root : $ProjectRoot"
Write-Host "Home dir     : $HomeDir"
Write-Host "Cfd home     : $CfdHome"
Write-Host "==============================================" -ForegroundColor Cyan

# ---- 2. 检查 Python ----
$Py = $null
foreach ($cand in @('python','py')) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) { $Py = $cmd.Source; break }
}
if (-not $Py) {
    Write-Host "ERROR: Python not found. Install Python 3.10+ and rerun." -ForegroundColor Red
    exit 1
}
Write-Host "Python: $Py ($(python --version 2>&1))"

# ---- 3. 创建 .venv 并安装依赖 ----
$Venv = Join-Path $ProjectRoot '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating venv at $Venv ..."
    python -m venv $Venv
    if (-not (Test-Path $VenvPython)) { Write-Host "ERROR: venv creation failed." -ForegroundColor Red; exit 1 }
}
$Req = Join-Path $ProjectRoot 'requirements.txt'
if (Test-Path $Req) {
    Write-Host "Installing dependencies from requirements.txt ..."
    & $VenvPython -m pip install --upgrade pip | Out-Null
    & $VenvPython -m pip install -r $Req
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: dependency install failed." -ForegroundColor Red; exit 1 }
} else {
    Write-Host "requirements.txt not found; skipping dependency install." -ForegroundColor Yellow
}
& $VenvPython -m pip install -e $ProjectRoot
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: editable project install failed." -ForegroundColor Red; exit 1 }

# ---- 4. 恢复 API_KEY ----
$SecretsSrc = Join-Path $ExtractionRoot '.secrets'
$SecretsDst = Join-Path $ProjectRoot '.secrets'
$ApiKeySrc = Join-Path $SecretsSrc 'API_KEY.txt'
$ApiKeyDst = Join-Path $SecretsDst 'API_KEY.txt'
if (Test-Path $ApiKeySrc) {
    New-Item -ItemType Directory -Force -Path $SecretsDst | Out-Null
    Copy-Item -LiteralPath $ApiKeySrc -Destination $ApiKeyDst -Force
    Write-Host "API key restored to $ApiKeyDst."
} else {
    New-Item -ItemType Directory -Force -Path $SecretsDst | Out-Null
    Set-Content -Path $ApiKeyDst -Value '' -Encoding UTF8
    Write-Host ""
    Write-Host "WARNING: .secrets\API_KEY.txt was not found in the archive." -ForegroundColor Yellow
    Write-Host "Place your Bearer token into: $ApiKeyDst" -ForegroundColor Yellow
    Write-Host "The token is read from this file at server start. Add it before relying on auth." -ForegroundColor Yellow
    Write-Host ""
}

# ---- 5. 恢复 Tunnel credentials 到 ~/.cloudflared ----
$CfdArchive = Join-Path $ExtractionRoot 'cloudflared'
if (Test-Path $CfdArchive) {
    New-Item -ItemType Directory -Force -Path $CfdHome | Out-Null
    Get-ChildItem -Path $CfdArchive -File | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $CfdHome -Force
        Write-Host "Restored cloudflared file: $($_.Name)"
    }
} else {
    Write-Host "WARNING: no 'cloudflared' folder in archive. Tunnel credentials not restored." -ForegroundColor Yellow
}

# ---- 6. 动态发现 cloudflared.exe ----
$Cf = $null
foreach ($probe in @(
    (Join-Path $env:ProgramFiles 'cloudflared\cloudflared.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'cloudflared\cloudflared.exe'),
    (Join-Path $CfdHome 'cloudflared.exe')
)) {
    if ($probe -and (Test-Path $probe)) { $Cf = $probe; break }
}
if (-not $Cf) {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { $Cf = $cmd.Source }
}
if (-not $Cf) {
    Write-Host "ERROR: cloudflared.exe not found. Install cloudflared first." -ForegroundColor Red
    exit 1
}
Write-Host "cloudflared: $Cf"

# ---- 7. 生成/恢复正确的 config.yml ----
# 若导出的 config.yml 已存在且含 machine-specific 路径，重写为动态路径。
$CfgPath = Join-Path $CfdHome 'config.yml'
$CfdCredJson = $null
# 从导出/现有的 config.yml 中读取 hostname 与 tunnel，而不是硬编码
$CfgHostname = ''
$CfgTunnel = ''
$ArchivedCfg = Join-Path $CfdArchive 'config.yml'
$CfgToRead = $ArchivedCfg
if (-not (Test-Path $CfgToRead)) { $CfgToRead = $CfgPath }
if (Test-Path $CfgToRead) {
    $oldCfgRaw = Get-Content -Raw -Path $CfgToRead
    if ($oldCfgRaw -match '(?m)^\s*-\s+hostname:\s*(\S+)') { $CfgHostname = $Matches[1] }
    if ($oldCfgRaw -match '(?m)^\s*tunnel:\s*(\S+)') { $CfgTunnel = $Matches[1] }
}
Get-ChildItem -Path $CfdHome -File -Filter '*.json' -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Name -ne 'cert.pem') { $CfdCredJson = $_.FullName }
}
if ($CfdCredJson) {
    $CfgContent = @"
tunnel: $CfgTunnel
credentials-file: $CfdCredJson
protocol: http2

ingress:
  - hostname: $CfgHostname
    service: $LocalOrigin
  - service: http_status:404
"@
    Set-Content -Path $CfgPath -Value $CfgContent -Encoding UTF8
    Write-Host "Wrote config.yml -> $CfgPath"
} else {
    Write-Host "WARNING: no tunnel credentials JSON found in ~/.cloudflared. config.yml not rewritten." -ForegroundColor Yellow
}

# ---- 8. 打印旧机器关闭确认，要求输入 YES ----
Write-Host ""
Write-Host "============================================================" -ForegroundColor Red
Write-Host "WARNING: Before starting the Named Tunnel on THIS machine," -ForegroundColor Red
Write-Host "confirm the OLD machine is OFF, or its DeskSense / cloudflared" -ForegroundColor Red
Write-Host "have been STOPPED. Running the same Named Tunnel from two" -ForegroundColor Red
Write-Host "machines would break or conflict with the public endpoint." -ForegroundColor Red
Write-Host "============================================================" -ForegroundColor Red
Write-Host ""
$confirmed = Read-Host 'Type exactly YES (without quotes) to continue and start the tunnel: '
if ($confirmed -ne 'YES') {
    Write-Host "Aborted. Nothing was started. Re-run when the old machine is off." -ForegroundColor Yellow
    exit 0
}

# ---- 9. 注册两个自启动任务 (交互用户 session) ----
function Register-Task {
    param([string]$TaskName, [System.Management.Automation.PSObject]$Action, [string]$Desc)
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    } catch { }
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $trigger -Settings $settings -Principal $principal -Description $Desc | Out-Null
    Write-Host "Registered autostart task: $TaskName" -ForegroundColor Green
}

# DeskSense MCP
$Python = Join-Path $Venv 'Scripts\python.exe'
$actionMcp = New-ScheduledTaskAction -Execute $Python -Argument '-m desksense.server' -WorkingDirectory $ProjectRoot
Register-Task -TaskName 'DeskSense MCP' -Action $actionMcp -Desc 'DeskSense MCP user-login autostart'

# Cloudflared Named Tunnel (复用导出的 start-named-tunnel.ps1)
$TunnelScript = Join-Path $ProjectRoot 'scripts\start-named-tunnel.ps1'
if (Test-Path $TunnelScript) {
    $actionTunnel = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$TunnelScript`"" `
        -WorkingDirectory $ProjectRoot
    Register-Task -TaskName 'Cloudflared Named Tunnel' -Action $actionTunnel -Desc 'Cloudflared Named Tunnel user-login autostart'
} else {
    Write-Host "WARNING: scripts\start-named-tunnel.ps1 not found; tunnel autostart not registered." -ForegroundColor Yellow
}

# ---- 10. 启动 DeskSense MCP server ----
Write-Host ""
Write-Host "Starting DeskSense MCP server ..."
$Logs = Join-Path $ProjectRoot 'logs'
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
Start-Process -FilePath $Python -ArgumentList @('-m','desksense.server') `
    -WorkingDirectory $ProjectRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Logs 'stdout.log') `
    -RedirectStandardError (Join-Path $Logs 'stderr.log')
Start-Sleep -Seconds 3
Write-Host "Server started at $LocalOrigin"

# ---- 11. 启动 Named Tunnel ----
if (Test-Path $TunnelScript) {
    Write-Host "Starting Cloudflared Named Tunnel ..."
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $TunnelScript
} else {
    Write-Host "Tunnel script not found; start it manually later." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "DeskSense MOVE install complete." -ForegroundColor Green
Write-Host "Local health : http://127.0.0.1:8765/healthz"
if ($CfgHostname) { Write-Host "Public MCP   : https://$CfgHostname/mcp" }
