# DeskSense — 停止脚本
# 用法: .\scripts\stop.ps1
$ErrorActionPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $PSScriptRoot
$Port = 8765
$ConfigPath = Join-Path $Root 'config.json'
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    $Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Config.port) { $Port = [int]$Config.port }
}

# 查找配置端口的 DeskSense 进程并结束
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen
if (-not $conns) {
    Write-Host "DeskSense 未在运行。"
    exit 0
}
$pids = $conns.OwningProcess | Sort-Object -Unique
foreach ($procPid in $pids) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $procPid"
    if (-not $processInfo.CommandLine -or -not $processInfo.CommandLine.Contains('desksense.server')) {
        Write-Host "拒绝停止 PID=$procPid：未验证为 DeskSense 进程。"
        exit 1
    }
    Stop-Process -Id $procPid -Force
    Write-Host "已停止进程 PID=$procPid"
}
Write-Host "DeskSense 已停止。"
