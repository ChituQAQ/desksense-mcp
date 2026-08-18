# DeskSense MOVE — 导出迁移包 (在旧电脑上运行)
# 用法: .\scripts\export-move.ps1
# 生成: dist\desksense-move-<timestamp>.zip
# 本脚本只导出迁移真正需要的文件，绝不导出 focus history DB。
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
if (Test-Path $SecretsSrc) {
    New-Item -ItemType Directory -Force -Path $SecretsDst | Out-Null
    Get-ChildItem -Path $SecretsSrc -File | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $SecretsDst -Force
    }
} else {
    Set-Content -Path (Join-Path $SecretsDst 'API_KEY.txt') -Value '' -Encoding UTF8
    Set-Content -Path $SensitiveFile -Value "WARNING: .secrets/API_KEY.txt was missing on the source machine. You must provide it on the destination." -Encoding UTF8
}

# ---- 拷贝 Named Tunnel credentials + config.yml ----
$TunnelStaging = Join-Path $Stage 'cloudflared'
New-Item -ItemType Directory -Force -Path $TunnelStaging | Out-Null

$TunnelId = ''
$Hostname = ''
if (Test-Path $CfdHome) {
    Get-ChildItem -Path $CfdHome -File | Where-Object { $_.Name -like '*.json' } | ForEach-Object {
        $dest = Join-Path $TunnelStaging $_.Name
        Copy-Item -Path $_.FullName -Destination $dest -Force
        try {
            $c = Get-Content -Raw -Path $_.FullName | ConvertFrom-Json
            if ($c.TunnelID) { $TunnelId = $c.TunnelID }
        } catch { }
    }
    if (Test-Path (Join-Path $CfdHome 'config.yml')) {
        Copy-Item -Path (Join-Path $CfdHome 'config.yml') -Destination $TunnelStaging -Force
    }
}

# 从 config.yml 读取 hostname / tunnel id 作为 manifest 补充
$StackedCfg = Join-Path $TunnelStaging 'config.yml'
if (Test-Path $StackedCfg) {
    $raw = Get-Content -Raw -Path $StackedCfg
    if ($raw -match 'hostname:\s*(\S+)') { $Hostname = $Matches[1] }
    if (-not $TunnelId -and $raw -match 'tunnel:\s*(\S+)') { $TunnelId = $Matches[1] }
}

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
    hostname    = $Hostname
    tunnel_id   = $TunnelId
    export_time = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
    git_commit  = $GitCommit
}
$ManifestObj | ConvertTo-Json | Set-Content -Path $Manifest -Encoding UTF8

# ---- SENSITIVE.txt (若尚未创建) ----
if (-not (Test-Path $SensitiveFile)) {
    $lines = @(
        '===================================================================='
        'THIS ARCHIVE CONTAINS SENSITIVE MATERIAL:'
        '  - .secrets/API_KEY.txt       (Bearer token for the MCP endpoint)'
        '  - cloudflared/*.json         (Named Tunnel credentials, secret key)'
        '  - cloudflared/config.yml     (Tunnel configuration)'
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
