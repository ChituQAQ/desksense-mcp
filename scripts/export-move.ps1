# DeskSense MOVE — 导出迁移包 (在旧电脑上运行)
# 用法: .\scripts\export-move.ps1
# 生成: dist\desksense-move-<timestamp>.zip
# 本脚本只导出迁移真正需要的文件：config.yml 引用的唯一 tunnel 凭据与
# 指向本项目端口的 DeskSense 路由片段；绝不导出 focus history DB，
# 也绝不打包 ~/.cloudflared 下未被引用的其他凭据或其他业务路由。
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$HomeDir = $env:USERPROFILE
if (-not $HomeDir) { $HomeDir = $env:HOMEDRIVE + $env:HOMEPATH }
$CfdHome = Join-Path $HomeDir '.cloudflared'
$Dist = Join-Path $Root 'dist'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$ZipName = "desksense-move-$Stamp.zip"
$ZipPath = Join-Path $Dist $ZipName
$Stage = Join-Path $env:TEMP "desksense-move-$Stamp"
$Manifest = Join-Path $Stage 'manifest.json'

New-Item -ItemType Directory -Force -Path $Dist | Out-Null
if (Test-Path $Stage) { Remove-Item -Path $Stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

# ---- 发现并拷贝项目代码/配置 ----
$ProjectStaging = Join-Path $Stage 'project'
New-Item -ItemType Directory -Force -Path $ProjectStaging | Out-Null

# 需要迁移的项目文件（相对 $Root）。不要包含 .venv / logs / data / dist / .secrets (单独处理)
$Items = @(
    'config.json',
    'requirements.txt',
    'requirements-dev.txt',
    'pyproject.toml',
    'README.md',
    '.gitignore'
)
foreach ($it in $Items) {
    $src = Join-Path $Root $it
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $ProjectStaging -Recurse -Force
    }
}

# Package source directory and common project entry points.
foreach ($pkg in @('desksense','src','server.py','main.py')) {
    $p = Join-Path $Root $pkg
    if (Test-Path $p) {
        Copy-Item -Path $p -Destination $ProjectStaging -Recurse -Force
    }
}
## 清理暂存区中的派生物（__pycache__ / *.egg-info），保持 ZIP 干净
Get-ChildItem -Path $ProjectStaging -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq '__pycache__' -or $_.Name -like '*.egg-info' } |
    ForEach-Object { Remove-Item -Path $_.FullName -Recurse -Force }

# ---- scripts (排除本导出脚本自身，避免循环包含) ----
$ScriptsDst = Join-Path $ProjectStaging 'scripts'
New-Item -ItemType Directory -Force -Path $ScriptsDst | Out-Null
Get-ChildItem -Path (Join-Path $Root 'scripts') -File | Where-Object { $_.Name -ne 'export-move.ps1' } | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $ScriptsDst -Force
}
# ---- 拷贝 secrets ----
$SecretsSrc = Join-Path $Root '.secrets'
$SecretsDst = Join-Path $Stage '.secrets'
$SensitiveFile = Join-Path $Stage 'SENSITIVE.txt'
New-Item -ItemType Directory -Force -Path $SecretsDst | Out-Null
if (Test-Path $SecretsSrc) {
    Get-ChildItem -Path $SecretsSrc -File | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $SecretsDst -Force
    }
} else {
    Set-Content -Path (Join-Path $SecretsDst 'API_KEY.txt') -Value '' -Encoding UTF8
    Set-Content -Path $SensitiveFile -Value "WARNING: .secrets/API_KEY.txt was missing on the source machine. You must provide it on the destination." -Encoding UTF8
}

# ---- Named Tunnel：只导出 config.yml 引用的那一个凭据 + DeskSense 本地路由 ----
# 契约（用户确认 2026-09-28）：绝不打包 ~/.cloudflared 下未被引用的其他凭据 JSON，
# 也不再复制整个 config.yml（共享隧道的其他业务路由不随包外发）。
$TunnelStaging = Join-Path $Stage 'cloudflared'
New-Item -ItemType Directory -Force -Path $TunnelStaging | Out-Null

$ConfigYml = Join-Path $CfdHome 'config.yml'
if (-not (Test-Path -LiteralPath $ConfigYml -PathType Leaf)) {
    Write-Host "ERROR: $ConfigYml not found; nothing to export for the Named Tunnel." -ForegroundColor Red
    exit 1
}
$RawCfg = Get-Content -Raw -LiteralPath $ConfigYml
$TunnelId = ''
if ($RawCfg -match '(?m)^\s*tunnel:\s*(\S+)') { $TunnelId = $Matches[1] }
if (-not $TunnelId) {
    Write-Host 'ERROR: config.yml has no tunnel: <id> line.' -ForegroundColor Red
    exit 1
}

$CredName = ''
if ($RawCfg -match '(?m)^\s*credentials-file:\s*(?:"([^"]+)"|(\S+))\s*$') {
    $CredPath0 = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
    $CredName = [System.IO.Path]::GetFileName($CredPath0)
}
if (-not $CredName) { $CredName = "$TunnelId.json" }
$CredPath = Join-Path $CfdHome $CredName
if (-not (Test-Path -LiteralPath $CredPath -PathType Leaf)) {
    Write-Host "ERROR: tunnel credential referenced by config.yml not found: $CredPath" -ForegroundColor Red
    exit 1
}
$Cred = Get-Content -Raw -LiteralPath $CredPath | ConvertFrom-Json
if ([string]$Cred.TunnelID -ne $TunnelId) {
    Write-Host 'ERROR: credential TunnelID does not match config.yml tunnel id; refusing to export.' -ForegroundColor Red
    exit 1
}
Copy-Item -LiteralPath $CredPath -Destination (Join-Path $TunnelStaging $CredName) -Force

# 从项目 config.json 读本地端口，挑选 ingress 中指向该端口的“本节点路由”。
$Port = 8765
$ProjectCfgPath = Join-Path $Root 'config.json'
if (Test-Path -LiteralPath $ProjectCfgPath -PathType Leaf) {
    $NodeCfg = Get-Content -Raw -LiteralPath $ProjectCfgPath | ConvertFrom-Json
    if ($NodeCfg.port) { $Port = [int]$NodeCfg.port }
}
$Routes = @()
$PendingHostname = ''
foreach ($Line in (Get-Content -LiteralPath $ConfigYml)) {
    if ($Line -match '^\s*-\s+hostname:\s*(\S+)') { $PendingHostname = $Matches[1]; continue }
    if ($PendingHostname -and $Line -match '^\s+service:\s*(\S+)') {
        $Service = $Matches[1]
        if ($Service -match '^https?://(?:127\.0\.0\.1|localhost):(\d+)' -and [int]$Matches[1] -eq $Port) {
            $Routes += [pscustomobject]@{ hostname = $PendingHostname; service = $Service }
        }
        $PendingHostname = ''
    }
}
if (-not $Routes) {
    Write-Host ("ERROR: no ingress route in config.yml points at local port $Port. " +
                'Fix the ingress entry or the project config.json port before exporting.') -ForegroundColor Red
    exit 1
}
$Hostname = $Routes[0].hostname

# ---- git commit ----
$GitCommit = ''
$gitExists = Get-Command git -ErrorAction SilentlyContinue
if ($gitExists) {
    try {
        $GitCommit = (git -C $Root rev-parse --short HEAD 2>$null).Trim()
    } catch { }
}

# ---- manifest.json ----
$ManifestObj = @{
    hostname         = $Hostname
    tunnel_id        = $TunnelId
    credentials_file = $CredName
    routes           = $Routes
    export_time      = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
    git_commit       = $GitCommit
}
$ManifestObj | ConvertTo-Json -Depth 4 | Set-Content -Path $Manifest -Encoding UTF8

# ---- SENSITIVE.txt (若尚未创建) ----
if (-not (Test-Path $SensitiveFile)) {
    $lines = @(
        '===================================================================='
        'THIS ARCHIVE CONTAINS SENSITIVE MATERIAL:'
        '  - .secrets\API_KEY.txt       (Bearer token for the MCP endpoint)'
        '  - cloudflared\<tunnel-id>.json (Named Tunnel credentials, secret key)'
        '  - manifest.json              (tunnel id, routes, machine metadata)'
        'Keep this ZIP private. Do not commit it to git. Do not share it.'
        '===================================================================='
    )
    Set-Content -Path $SensitiveFile -Value $lines -Encoding UTF8
}

# ---- 打包 ZIP ----
Compress-Archive -Path (Join-Path $Stage '*') -DestinationPath $ZipPath -Force

# ---- 不打印 secrets，仅报告结构 ----
Write-Host ''
Write-Host 'DeskSense MOVE export complete.' -ForegroundColor Green
Write-Host "ZIP: $ZipPath"
Write-Host ''
Write-Host 'Contents (file names only):'
Get-ChildItem -Path $Stage -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($Stage.Length + 1)
    Write-Host "  $rel"
}
Write-Host ''
Write-Host 'Manifest:'
Get-Content -Raw $Manifest
Write-Host ''
Write-Host 'Next: copy this ZIP to the new PC, extract it, then run project\scripts\install-move.ps1.' -ForegroundColor Cyan
# 显式成功退出：git 等原生命令的失败码不应泄漏为本脚本的退出码。
exit 0
