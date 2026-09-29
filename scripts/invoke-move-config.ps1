# Shared Python dependency preflight for MOVE. Does not install anything.
[CmdletBinding()]
param([Parameter(Mandatory = $true)] [string[]]$Arguments)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Command = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $Command) { throw 'MOVE requires the Node venv or Python 3.11-3.14 on PATH.' }
    $Python = $Command.Source
}
& $Python -I -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('yaml') else 1)"
if ($LASTEXITCODE -ne 0) {
    throw 'MOVE requires PyYAML. Install the updated project requirements into the Node venv first.'
}
$Output = @(& $Python -I (Join-Path $PSScriptRoot 'move-config.py') @Arguments)
if ($LASTEXITCODE -ne 0) { throw ($Output -join "`n") }
$Output | Write-Output
