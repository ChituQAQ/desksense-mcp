# PC Sense MCP — 本地启动脚本
# 用法: .\scripts\start.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$Src = Join-Path $Root 'src'

# 检查是否已在运行
$existing = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "PC Sense MCP 已在运行 (PID 列表: $($existing.OwningProcess))"
    exit 0
}

if (-not (Test-Path $Python)) {
    Write-Error "未找到 venv Python: $Python"
    exit 1
}

$env:PYTHONPATH = $Src
try {
    Start-Process -FilePath $Python -ArgumentList @('-m', 'pc_sense.server') `
        -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Root 'logs\stdout.log') `
        -RedirectStandardError (Join-Path $Root 'logs\stderr.log')
    Write-Host "PC Sense MCP 已后台启动。"
    Write-Host "健康检查: http://127.0.0.1:8765/healthz"
} catch {
    Write-Error "启动失败: $_"
    exit 1
}