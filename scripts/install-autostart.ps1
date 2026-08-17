# PC Sense MCP — 注册用户登录自启动 (Task Scheduler)
# 幂等：同一任务名重复执行会覆盖。
# 运行在当前用户交互会话（登录后启动），不做 SYSTEM / Session 0。
# 用法: .\scripts\install-autostart.ps1
$ErrorActionPreference = 'Stop'
$TaskName = 'PC Sense MCP'

$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$Src = Join-Path $Root 'src'

if (-not (Test-Path $Python)) {
    Write-Error "未找到 venv Python: $Python"
    exit 1
}

# 幂等：先删除已有任务
schtasks /Delete /F /TN $TaskName 2>$null | Out-Null

$action = New-ScheduledTaskAction -Execute $Python -Argument "-m pc_sense.server" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'PC Sense MCP 用户登录自启动（只读电脑感知）' | Out-Null
Write-Host "已注册自启动任务: $TaskName"