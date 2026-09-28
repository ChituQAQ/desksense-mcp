# Stop only this Node's dedicated launchers, then its servers (also between retries).
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Launcher = Join-Path $Root 'scripts\start.ps1'

function Get-PathArgumentPattern([string]$Path) {
    $Escaped = [regex]::Escape($Path)
    # Unquoted paths containing spaces are not one native command-line argument.
    if ($Path -match '\s') { return '"' + $Escaped + '"' }
    return '(?:"' + $Escaped + '"|' + $Escaped + ')'
}

# Recognize only a dedicated -File host. Never kill an interactive shell or a
# -Command/-EncodedCommand host merely mentioning the launcher in its source.
$HostArgument = '(?:"[^"]+"|[^\s"]+)\s+'
$HostOptions = '(?:(?:-(?:NoProfile|NonInteractive|NoLogo|STA|MTA)\s+)|(?:-(?:ExecutionPolicy|WindowStyle|InputFormat|OutputFormat)\s+(?:"[^"]+"|[^\s"]+)\s+))*'
$LauncherPattern = '^' + $HostArgument + $HostOptions + '-File\s+' + (Get-PathArgumentPattern $Launcher) + '(?:\s|$)'
$ServerPattern = '^' + (Get-PathArgumentPattern $Python) + '\s+-m\s+desksense\.server(?:\s|$)'

function Stop-NodeProcesses {
    param([string[]]$Names, [string]$Pattern)
    $Filter = ($Names | ForEach-Object { "Name = '$_'" }) -join ' OR '
    $Candidates = @(Get-CimInstance Win32_Process -Filter $Filter | Where-Object {
        $_.ProcessId -ne $PID -and $_.Name -in $Names -and $_.CommandLine -match $Pattern
    })
    foreach ($Info in $Candidates) {
        $Process = $null
        try {
            $Process = Get-Process -Id $Info.ProcessId -ErrorAction SilentlyContinue
            if (-not $Process) { continue } # It may have exited after enumeration.
            # Retain this process identity, then recheck the command line before
            # terminating it. Do not act on a stale PID that now belongs elsewhere.
            $null = $Process.Handle
            if ($Process.HasExited) { continue }
            $Current = Get-CimInstance Win32_Process -Filter "ProcessId = $($Info.ProcessId)"
            if (-not $Current -or $Current.Name -notin $Names -or $Current.CommandLine -notmatch $Pattern) {
                continue
            }
            if (-not $Process.HasExited) { Stop-Process -InputObject $Process -Force }
            if (-not $Process.WaitForExit(10000)) {
                throw "Timed out stopping DeskSense process PID=$($Info.ProcessId)."
            }
            Write-Host "Stopped DeskSense process PID=$($Info.ProcessId)."
        } finally {
            if ($Process) { $Process.Dispose() }
        }
    }
}

try {
    # A failed launcher stop must prevent killing its server, otherwise supervision
    # would undo the explicit stop. Query servers only after launchers have exited.
    Stop-NodeProcesses -Names @('powershell.exe', 'pwsh.exe') -Pattern $LauncherPattern
    Stop-NodeProcesses -Names @('python.exe', 'pythonw.exe') -Pattern $ServerPattern
    Write-Host 'DeskSense is stopped. Login autostart registration is unchanged.'
    exit 0
} catch {
    Write-Error "Could not stop DeskSense: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
}
