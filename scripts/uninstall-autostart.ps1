# PC Sense MCP — 移除自启动任务
# 用法: .\scripts\uninstall-autostart.ps1
$ErrorActionPreference = 'SilentlyContinue'
$TaskName = 'PC Sense MCP'
schtasks /Delete /F /TN $TaskName 2>$null | Out-Null
Write-Host "已移除自启动任务: $TaskName (若不存在则忽略)"