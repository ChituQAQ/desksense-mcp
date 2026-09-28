# DeskSense MOVE — 迁移安装 (在新电脑解压目录中运行)
# 用法: 解压 desksense-move-<ts>.zip 后，在解压出的项目根目录运行:
#        .\scripts\install-move.ps1
# 本脚本推导项目根目录、动态发现环境，不硬编码项目路径或用户目录。
# -MergeIngress：仅当目标机已存在同一 tunnel 的 config.yml 时，非破坏性追加缺失路由。
[CmdletBinding()]
param([switch]$MergeIngress)
$ErrorActionPreference = 'Stop'

# ---- 1. 推导解压目录与项目根目录（archive root -> project -> scripts） ----
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ExtractionRoot = Split-Path -Parent $ProjectRoot
$HomeDir = $env:USERPROFILE
if (-not $HomeDir) { $HomeDir = Join-Path $env:HOMEDRIVE $env:HOMEPATH }
$CfdHome = Join-Path $HomeDir '.cloudflared'
# 本地端口随迁移来的 config.json 走（与旧机一致），不再硬编码。
$LocalPort = 8765
$NodeCfgPath = Join-Path $ProjectRoot 'config.json'
if (Test-Path -LiteralPath $NodeCfgPath -PathType Leaf) {
    $NodeCfg = Get-Content -Raw -LiteralPath $NodeCfgPath | ConvertFrom-Json
    if ($NodeCfg.port) { $LocalPort = [int]$NodeCfg.port }
}
$LocalOrigin = "http://127.0.0.1:$LocalPort"

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

# ---- 5. 校验迁移包结构（凭据与 config.yml 在步骤 7 统一恢复） ----
$ManifestPath = Join-Path $ExtractionRoot 'manifest.json'
$CfdArchive = Join-Path $ExtractionRoot 'cloudflared'
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    Write-Host "ERROR: manifest.json not found in archive root: $ExtractionRoot" -ForegroundColor Red
    exit 1
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

# ---- 7. 恢复 tunnel 凭据与 config.yml（按 manifest 隧道 ID 精确匹配；冲突默认拒绝） ----
# 契约细节见 restore-tunnel-config.ps1 头部注释。
$RestoreScript = Join-Path $ProjectRoot 'scripts\restore-tunnel-config.ps1'
if (-not (Test-Path -LiteralPath $RestoreScript -PathType Leaf)) {
    Write-Host "ERROR: $RestoreScript not found." -ForegroundColor Red
    exit 1
}
& $RestoreScript -ManifestFile $ManifestPath -ArchiveCfdDir $CfdArchive -CfdHome $CfdHome -MergeIngress:$MergeIngress
$Manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
$CfgHostname = ''
if ($Manifest.routes) {
    $FirstRoute = @($Manifest.routes)[0]
    if ($FirstRoute.hostname) { $CfgHostname = [string]$FirstRoute.hostname }
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

# ---- 9. 注册自启动任务（复用项目脚本，与全新安装共用同一加固链路） ----
$InstallAutostart = Join-Path $ProjectRoot 'scripts\install-autostart.ps1'
if (-not (Test-Path -LiteralPath $InstallAutostart -PathType Leaf)) {
    Write-Host "ERROR: $InstallAutostart not found." -ForegroundColor Red
    exit 1
}
& $InstallAutostart
$TunnelAutostart = Join-Path $ProjectRoot 'scripts\install-tunnel-autostart.ps1'
if (Test-Path -LiteralPath $TunnelAutostart -PathType Leaf) {
    & $TunnelAutostart
} else {
    Write-Host "WARNING: scripts\install-tunnel-autostart.ps1 not found; tunnel autostart not registered." -ForegroundColor Yellow
}

# ---- 10. 启动 DeskSense MCP server（复用带身份/健康校验的启动器） ----
Write-Host ""
Write-Host "Starting DeskSense MCP server ..."
& (Join-Path $ProjectRoot 'scripts\start.ps1')
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: start.ps1 failed; see logs\startup.log." -ForegroundColor Red
    exit 1
}
Write-Host "Server started at $LocalOrigin"

# ---- 11. 启动 Named Tunnel ----
$TunnelScript = Join-Path $ProjectRoot 'scripts\start-named-tunnel.ps1'
if (Test-Path -LiteralPath $TunnelScript) {
    Write-Host "Starting Cloudflared Named Tunnel ..."
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $TunnelScript
} else {
    Write-Host "Tunnel script not found; start it manually later." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "DeskSense MOVE install complete." -ForegroundColor Green
Write-Host "Local health : $LocalOrigin/healthz"
if ($CfgHostname) { Write-Host "Public MCP   : https://$CfgHostname/mcp" }
