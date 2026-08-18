# DeskSense — 本地启动脚本
# 用法: .\scripts\start.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$Port = 8765
$ConfigPath = Join-Path $Root 'config.json'
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    $Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Config.port) { $Port = [int]$Config.port }
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root 'logs') | Out-Null

# 检查是否已在运行
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "DeskSense 已在运行 (监听进程: $($existing.OwningProcess))"
    exit 0
}

if (-not (Test-Path $Python)) {
    Write-Error "未找到 venv Python: $Python"
    exit 1
}

try {
    Start-Process -FilePath $Python -ArgumentList @('-m', 'desksense.server') `
        -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Root 'logs\stdout.log') `
        -RedirectStandardError (Join-Path $Root 'logs\stderr.log')
    Start-Sleep -Seconds 2
    Write-Host "DeskSense 已后台启动。"
    Write-Host "健康检查: http://127.0.0.1:$Port/healthz"
    Write-Host "MCP URL  : http://127.0.0.1:$Port/mcp"
} catch {
    Write-Error "启动失败: $_"
    exit 1
}
