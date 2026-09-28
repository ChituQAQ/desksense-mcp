# Cloudflared Named Tunnel - register user-login autostart (Task Scheduler)
# Idempotent: overwrites the same task name with -Force.
$ErrorActionPreference = 'Stop'
$TaskName = 'Cloudflared Named Tunnel'

$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root 'scripts\start-named-tunnel.ps1'
if (-not (Test-Path $Script)) { Write-Host "ERROR: $Script not found" -ForegroundColor Red; exit 1 }

# Register with -Force below; do not delete the working task before replacement.
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force `
        -Description 'Cloudflared Named Tunnel user-login autostart' | Out-Null
    Write-Host "Registered autostart task: $TaskName" -ForegroundColor Green
} catch {
    Write-Host "ERROR: registration failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}