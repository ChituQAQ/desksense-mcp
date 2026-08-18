[CmdletBinding()]
param(
    [string]$Version,
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Root = Split-Path -Parent $PSScriptRoot
if (-not $Version) {
    $ProjectFile = Join-Path $Root 'pyproject.toml'
    $ProjectText = [System.IO.File]::ReadAllText($ProjectFile)
    $VersionMatch = [regex]::Match($ProjectText, '(?m)^version\s*=\s*"([^"]+)"\s*$')
    if (-not $VersionMatch.Success) { throw 'Unable to read project.version from pyproject.toml.' }
    $Version = $VersionMatch.Groups[1].Value
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Release version must use MAJOR.MINOR.PATCH format: $Version"
}
if (-not $OutputPath) { $OutputPath = Join-Path $Root "dist\DeskSense-v$Version.zip" }
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$Dist = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $Dist | Out-Null

$Git = Get-Command git.exe -ErrorAction Stop
$Tracked = @(& $Git.Source -C $Root ls-files)
if ($LASTEXITCODE -ne 0 -or $Tracked.Count -eq 0) { throw 'Unable to read git tracked files.' }
$Forbidden = @('.git/', '.venv/', '.secrets/', 'config.json', 'data/', 'logs/', 'dist/', '__pycache__/', '.pytest_cache/', '.egg-info/', 'cert.pem', 'desksense-move-')
foreach ($path in $Tracked) {
    $normalized = $path.Replace('\', '/')
    foreach ($pattern in $Forbidden) {
        if ($normalized -like "*$pattern*") { throw "Refusing to package forbidden path: $path" }
    }
}

if (Test-Path -LiteralPath $OutputPath) { Remove-Item -LiteralPath $OutputPath -Force }
& $Git.Source -C $Root archive --format=zip --output=$OutputPath HEAD
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) { throw 'git archive failed.' }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($OutputPath)
try {
    $names = @($zip.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
    foreach ($name in $names) {
        foreach ($pattern in $Forbidden) {
            if ($name -like "*$pattern*") { throw "Release ZIP contains forbidden path: $name" }
        }
    }
    Write-Host "Created: $OutputPath"
    Write-Host 'Contents:'
    $names | Sort-Object | ForEach-Object { Write-Host "  $_" }
    Write-Host 'Security check: passed (no runtime or private files).'
} finally { $zip.Dispose() }
