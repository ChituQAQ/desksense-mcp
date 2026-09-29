# Restore exactly one credential and validated ingress; never rewrite another tunnel.
# Same-tunnel merges require -MergeIngress and preserve all existing config bytes.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$ManifestFile,
    [Parameter(Mandatory = $true)] [string]$ArchiveCfdDir,
    [Parameter(Mandatory = $true)] [string]$CfdHome,
    [switch]$MergeIngress,
    [string]$CloudflaredExe
)
$ErrorActionPreference = 'Stop'
$MoveArgs = @('restore', '--manifest', $ManifestFile, '--archive', $ArchiveCfdDir, '--home', $CfdHome)
if ($MergeIngress) { $MoveArgs += '--merge' }
if (-not $CloudflaredExe) {
    $Command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if ($Command) { $CloudflaredExe = $Command.Source }
}
if ($CloudflaredExe) {
    $MoveArgs += @('--cloudflared', $CloudflaredExe)
} else {
    Write-Warning 'cloudflared not found: only structural/semantic checks will run. Validate ingress before starting a connector.'
}
& (Join-Path $PSScriptRoot 'invoke-move-config.ps1') -Arguments $MoveArgs
