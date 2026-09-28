# DeskSense local launcher. -Wait keeps Task Scheduler attached to the server.
# On unexpected server death the launcher retries inside the same task: Task
# Scheduler's restart-on-failure policy does not treat an action exiting with a
# non-zero code as a failure (verified on Windows 11 23H2: event 102 records the
# instance as completed), so retrying here is the only reliable recovery.
[CmdletBinding()]
param(
    [switch]$Wait,
    [int]$MaxRetries = 3,
    [int]$RetryDelaySeconds = 60
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Logs = Join-Path $Root 'logs'
$ServerProcess = $null
$StartedHere = $false
$ReadinessFailure = ''
# A non-Wait run is a one-shot start (install/manual use) and must stay fast.
if (-not $Wait) { $MaxRetries = 0 }
if ($RetryDelaySeconds -lt 1) { $RetryDelaySeconds = 1 }
if ($MaxRetries -lt 0) { $MaxRetries = 0 }

function Get-Listener {
    return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Assert-DeskSenseListener {
    param([object[]]$Listeners)
    if ($Listeners.Count -eq 0) { throw "No listener on port $Port." }
    $ExpectedPython = [regex]::Escape($Python)
    foreach ($ListenerPid in @($Listeners.OwningProcess | Sort-Object -Unique)) {
        $Info = Get-CimInstance Win32_Process -Filter "ProcessId = $ListenerPid"
        # A venv may use a base-python child process; its argv still starts with the venv path.
        if (-not $Info.CommandLine -or
            $Info.CommandLine -notmatch ('^"?' + $ExpectedPython + '"?\s+-m\s+desksense\.server(?:\s|$)')) {
            throw "Port $Port is occupied by a different process (PID=$ListenerPid); refusing to start."
        }
    }
    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 2
    if ($Health.ok -ne $true -or $Health.service -ne 'DeskSense MCP') {
        throw "Port $Port did not return a DeskSense health response."
    }
}

function Write-StartupLog([string]$Message) {
    Add-Content -LiteralPath (Join-Path $Logs 'startup.log') -Encoding UTF8 `
        -Value "$(Get-Date -Format o) $Message"
}

function Start-DeskSense {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Venv Python was not found: $Python"
    }
    # Every Start-Process truncates redirected files, including automatic retries.
    # Keep the immediately preceding attempt before opening the next pair of logs.
    if ($script:ServerProcess) {
        $script:ServerProcess.Dispose()
        $script:ServerProcess = $null
    }
    foreach ($Name in @('stdout.log', 'stderr.log')) {
        $Path = Join-Path $Logs $Name
        if (Test-Path -LiteralPath $Path) {
            Move-Item -LiteralPath $Path -Destination "$Path.previous" -Force
        }
    }
    $script:ServerProcess = Start-Process -FilePath $Python -ArgumentList @('-m', 'desksense.server') `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Logs 'stdout.log') `
        -RedirectStandardError (Join-Path $Logs 'stderr.log')
    $script:StartedHere = $true
    # Windows PowerShell 5.1 can lose ExitCode unless the native handle is retained.
    $null = $script:ServerProcess.Handle
}

function Wait-ServerReady {
    # $false means a retryable failure; the reason is in $script:ReadinessFailure.
    $Deadline = [DateTime]::UtcNow.AddSeconds(30)
    $LastFailure = 'No listener yet.'
    while ($true) {
        $script:ServerProcess.Refresh()
        if ($script:ServerProcess.HasExited) {
            $script:ReadinessFailure = "DeskSense exited before becoming healthy (exit=$($script:ServerProcess.ExitCode)); see logs\stderr.log."
            return $false
        }
        try {
            Assert-DeskSenseListener @(Get-Listener)
            return $true
        } catch {
            $LastFailure = $_.Exception.Message
        }
        if ([DateTime]::UtcNow -ge $Deadline) {
            $script:ReadinessFailure = "DeskSense health check timed out: $LastFailure"
            return $false
        }
        Start-Sleep -Milliseconds 250
    }
}

try {
    New-Item -ItemType Directory -Force -Path $Logs | Out-Null
    $Port = 8765
    $ConfigPath = Join-Path $Root 'config.json'
    if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
        $Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -ne $Config.port) { $Port = [int]$Config.port }
    }
    if ($Port -lt 1 -or $Port -gt 65535) { throw 'Configured port must be between 1 and 65535.' }

    $RetriesLeft = $MaxRetries
    $FinalExitCode = 1
    while ($true) {
        $Existing = @(Get-Listener)
        if ($Existing.Count -gt 0) {
            # Foreign listeners and identity/health mismatches are not retryable.
            Assert-DeskSenseListener $Existing
            Write-Host "DeskSense is already healthy on port $Port."
            if (-not $Wait) { exit 0 }
            # An independently started server must not leave a successful but unmonitored task.
            try {
                Wait-Process -Id @($Existing.OwningProcess | Sort-Object -Unique)
                $Failure = 'The existing DeskSense process exited.'
            } catch {
                $Failure = "Waiting on the existing DeskSense process failed: $($_.Exception.Message)"
            }
        } else {
            Start-DeskSense
            if (Wait-ServerReady) {
                Write-Host "DeskSense is healthy: http://127.0.0.1:$Port/mcp"
                if (-not $Wait) { exit 0 }
                $script:ServerProcess.WaitForExit()
                $ExitCode = $script:ServerProcess.ExitCode
                if ($null -eq $ExitCode) {
                    $Failure = 'Server exited without a readable exit code.'
                } else {
                    Write-StartupLog "Server exited with code $ExitCode."
                    if ($ExitCode -eq 0) { exit 0 }
                    # Normalize Windows termination/NTSTATUS codes; keep the raw value in the log.
                    $FinalExitCode = if ($ExitCode -lt 0) { 1 } else { $ExitCode }
                    $Failure = "Server exited with code $ExitCode."
                }
            } else {
                $Failure = $script:ReadinessFailure
                if ($script:ServerProcess -and -not $script:ServerProcess.HasExited) {
                    & "$env:WINDIR\System32\taskkill.exe" /PID $script:ServerProcess.Id /T /F 2>$null | Out-Null
                }
            }
        }
        if ($RetriesLeft -le 0) {
            Write-StartupLog "Giving up after exhausting retries: $Failure"
            exit $FinalExitCode
        }
        $RetriesLeft--
        Write-StartupLog "$Failure Retrying in $RetryDelaySeconds seconds ($RetriesLeft retries left)."
        $script:StartedHere = $false
        Start-Sleep -Seconds $RetryDelaySeconds
    }
} catch {
    # Never terminate a pre-existing listener or another project's process.
    if ($StartedHere -and $ServerProcess -and -not $ServerProcess.HasExited) {
        & "$env:WINDIR\System32\taskkill.exe" /PID $ServerProcess.Id /T /F 2>$null | Out-Null
    }
    $Message = $_.Exception.Message
    if (Test-Path -LiteralPath $Logs -PathType Container) {
        Add-Content -LiteralPath (Join-Path $Logs 'startup.log') -Encoding UTF8 `
            -Value "$(Get-Date -Format o) Launch failed: $Message"
    }
    Write-Error $Message -ErrorAction Continue
    exit 1
} finally {
    if ($ServerProcess) { $ServerProcess.Dispose() }
}
