# DeskSense — 停止脚本
# 用法: .\scripts\stop.ps1
$ErrorActionPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $PSScriptRoot

# 查找监听 8765 端口的进程并结束
$conns = Get-NetTCPConnection -LocalPort 8765 -State Listen
if (-not $conns) {
    Write-Host "DeskSense 未在运行。"
    exit 0
}
$pids = $conns.OwningProcess | Sort-Object -Unique
foreach ($procPid in $pids) {
    Stop-Process -Id $procPid -Force
    Write-Host "已停止进程 PID=$procPid"
}
Write-Host "DeskSense 已停止。"