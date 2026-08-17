# PC Sense MCP — 停止脚本
# 用法: .\scripts\stop.ps1
$ErrorActionPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $PSScriptRoot

# 查找监听 8765 端口的进程并结束
$conns = Get-NetTCPConnection -LocalPort 8765 -State Listen
if (-not $conns) {
    Write-Host "PC Sense MCP 未在运行。"
    exit 0
}
$pids = $conns.OwningProcess | Sort-Object -Unique
foreach ($pid in $pids) {
    Stop-Process -Id $pid -Force
    Write-Host "已停止进程 PID=$pid"
}
Write-Host "PC Sense MCP 已停止。"