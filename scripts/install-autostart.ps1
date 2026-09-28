# DeskSense — 注册用户登录自启动 (Task Scheduler)
# 幂等：同一任务名重复执行会覆盖。
# 运行在当前用户交互会话（登录后启动），不做 SYSTEM / Session 0。
# 用法: .\scripts\install-autostart.ps1
$ErrorActionPreference = 'Stop'
$TaskName = 'DeskSense MCP'

$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $Python)) {
    Write-Host "ERROR: 未找到 venv Python: $Python" -ForegroundColor Red
    exit 1
}

# 无窗口启动链: Task Scheduler -> wscript.exe -> run-desksense-hidden.vbs -> python -m desksense.server
$Wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$Launcher = Join-Path $PSScriptRoot 'run-desksense-hidden.vbs'
if (-not (Test-Path $Wscript)) {
    Write-Host "ERROR: 未找到 wscript.exe: $Wscript" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Launcher)) {
    Write-Host "ERROR: 未找到启动器: $Launcher" -ForegroundColor Red
    exit 1
}

# Register with -Force below; do not delete the working task before replacement.
$LauncherArgs = "//B //NoLogo `"$Launcher`" `"$Python`" `"$Root`""
$action = New-ScheduledTaskAction -Execute $Wscript -Argument $LauncherArgs -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -Description 'DeskSense MCP user-login autostart (read-only PC sensing)' | Out-Null
    Write-Host "已注册自启动任务: $TaskName" -ForegroundColor Green
} catch {
    Write-Host "ERROR: 注册失败: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

