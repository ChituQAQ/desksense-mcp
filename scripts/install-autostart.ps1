# DeskSense — 注册用户登录自启动 (Task Scheduler)
# 幂等：同一任务名重复执行会覆盖。
# 运行在当前用户交互会话（登录后启动），不做 SYSTEM / Session 0。
# 用法: .\scripts\install-autostart.ps1
$ErrorActionPreference = 'Continue'
$TaskName = 'DeskSense MCP'

$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$Src
if (-not (Test-Path $Python)) {
    Write-Host "ERROR: 未找到 venv Python: $Python" -ForegroundColor Red
    exit 1
}

# 幂等：删除已有同名任务（忽略"不存在"错误）
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {
    # 忽略：任务不存在
}

$action = New-ScheduledTaskAction -Execute $Python -Argument '-m desksense.server' -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'DeskSense MCP user-login autostart (read-only PC sensing)' | Out-Null
    Write-Host "已注册自启动任务: $TaskName" -ForegroundColor Green
} catch {
    Write-Host "ERROR: 注册失败: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

