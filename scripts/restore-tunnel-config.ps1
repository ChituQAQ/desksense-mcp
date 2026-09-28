# DeskSense MOVE — restore the tunnel credential and config.yml (called by install-move.ps1)
# Contract (user-approved 2026-09-28):
#   - Copy exactly ONE credential JSON, matched by the manifest's tunnel_id.
#   - Fresh target (no config.yml): write tunnel + credentials-file + manifest
#     routes + catch-all 404.
#   - Existing config.yml for a DIFFERENT tunnel: refuse, even with -MergeIngress
#     (one config.yml serves exactly one tunnel).
#   - Existing config.yml for the SAME tunnel: refuse unless -MergeIngress; the
#     merge appends only missing routes before the catch-all and never rewrites
#     existing lines.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$ManifestFile,
    [Parameter(Mandatory = $true)] [string]$ArchiveCfdDir,
    [Parameter(Mandatory = $true)] [string]$CfdHome,
    [switch]$MergeIngress
)
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ManifestFile -PathType Leaf)) {
    throw "Archive manifest not found: $ManifestFile"
}
$Manifest = Get-Content -Raw -LiteralPath $ManifestFile | ConvertFrom-Json
$TunnelId = [string]$Manifest.tunnel_id
if (-not $TunnelId) { throw 'manifest.json has no tunnel_id; re-export with export-move.ps1.' }

$CredentialName = [string]$Manifest.credentials_file
if (-not $CredentialName) { $CredentialName = "$TunnelId.json" }
$CredentialSrc = Join-Path $ArchiveCfdDir $CredentialName
if (-not (Test-Path -LiteralPath $CredentialSrc -PathType Leaf)) {
    throw "Tunnel credential not found in archive: $CredentialName"
}
$Credential = Get-Content -Raw -LiteralPath $CredentialSrc | ConvertFrom-Json
if ([string]$Credential.TunnelID -ne $TunnelId) {
    throw "Credential TunnelID does not match manifest tunnel_id ($([string]$Credential.TunnelID) != $TunnelId); refusing to install."
}

$Routes = @()
foreach ($Route in @($Manifest.routes)) {
    if ($Route -and $Route.hostname -and $Route.service) {
        $Routes += [pscustomobject]@{
            hostname = [string]$Route.hostname
            service  = [string]$Route.service
        }
    }
}
$LegacyCfg = Join-Path $ArchiveCfdDir 'config.yml'
if ($Routes.Count -eq 0) {
    # Older exports shipped the full config.yml and no route manifest.
    if (Test-Path -LiteralPath $LegacyCfg -PathType Leaf) {
        Write-Host 'WARNING: archive manifest has no routes (older export). Falling back to the first route in the archived config.yml.' -ForegroundColor Yellow
        $Pending = ''
        foreach ($Line in (Get-Content -LiteralPath $LegacyCfg)) {
            if ($Line -match '^\s*-\s+hostname:\s*(\S+)') { $Pending = $Matches[1]; continue }
            if ($Pending -and $Line -match '^\s+service:\s*(\S+)') {
                $Routes += [pscustomobject]@{ hostname = $Pending; service = $Matches[1] }
                break
            }
        }
        if ($Routes.Count -eq 0) { throw 'Archived config.yml has no ingress route to restore.' }
    } else {
        throw 'manifest.json has no routes and the archive contains no config.yml; re-export with export-move.ps1.'
    }
}

$CfgPath = Join-Path $CfdHome 'config.yml'
$ExistingTunnel = ''
if (Test-Path -LiteralPath $CfgPath -PathType Leaf) {
    $ExistingRaw = Get-Content -Raw -LiteralPath $CfgPath
    if ($ExistingRaw -match '(?m)^\s*tunnel:\s*(\S+)') { $ExistingTunnel = $Matches[1] }
    if ($ExistingTunnel -ne $TunnelId) {
        throw ("~\.cloudflared\config.yml already exists for tunnel '$ExistingTunnel' but this archive is for tunnel " +
               "'$TunnelId'. One config.yml serves exactly one tunnel; move the existing file aside or run the " +
               'two tunnels with separate --config files.')
    }
    if (-not $MergeIngress) {
        throw ("~\.cloudflared\config.yml already exists for tunnel '$TunnelId'. Re-run with -MergeIngress to " +
               'append only missing routes, or move the existing file aside for a fresh write.')
    }
}

# All checks passed; only now mutate anything.
New-Item -ItemType Directory -Force -Path $CfdHome | Out-Null
$CredentialDst = Join-Path $CfdHome $CredentialName
Copy-Item -LiteralPath $CredentialSrc -Destination $CredentialDst -Force
Write-Host "Restored tunnel credential: $CredentialName"

if (Test-Path -LiteralPath $CfgPath -PathType Leaf) {
    $Lines = [System.Collections.Generic.List[string]]([string[]](Get-Content -LiteralPath $CfgPath))
    $ExistingHostnames = @{}
    foreach ($Line in $Lines) {
        if ($Line -match '^\s*-\s+hostname:\s*(\S+)') { $ExistingHostnames[$Matches[1]] = $true }
    }
    $Missing = @($Routes | Where-Object { -not $ExistingHostnames.ContainsKey($_.hostname) })
    foreach ($Kept in @($Routes | Where-Object { $ExistingHostnames.ContainsKey($_.hostname) })) {
        Write-Host "Route '$($Kept.hostname)' already exists in config.yml; left unchanged." -ForegroundColor Yellow
    }
    if ($Missing.Count -eq 0) {
        Write-Host 'All archive routes already present in config.yml; nothing to merge.'
        exit 0
    }
    # 沿用目标文件中列表项的缩进（优先参考 catch-all 行，其次任意 - 开头行）。
    $Indent = '  '
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match '^(\s*)-\s+') { $Indent = $Matches[1]; break }
    }
    if ($null -ne $CatchAllIndex -and $Lines[$CatchAllIndex] -match '^(\s*)-\s+') {
        $Indent = $Matches[1]
    }
    $Block = @()
    foreach ($Route in $Missing) {
        $Block += "$Indent- hostname: $($Route.hostname)"
        $Block += "$Indent  service: $($Route.service)"
    }
    $CatchAllIndex = $null
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match '^\s*-\s+service:\s*http_status:') { $CatchAllIndex = $i; break }
    }
    if ($null -ne $CatchAllIndex) {
        $Lines.InsertRange($CatchAllIndex, [string[]]$Block)
    } else {
        $Lines.AddRange([string[]]$Block)
    }
    Set-Content -LiteralPath $CfgPath -Value ([string[]]$Lines) -Encoding UTF8
    Write-Host "Merged $($Missing.Count) route(s) into $CfgPath (existing routes untouched)."
} else {
    $Ingress = @()
    foreach ($Route in $Routes) {
        $Ingress += "  - hostname: $($Route.hostname)"
        $Ingress += "    service: $($Route.service)"
    }
    $Ingress += '  - service: http_status:404'
    $CfgContent = @"
tunnel: $TunnelId
credentials-file: $CredentialDst
protocol: http2

ingress:
$($Ingress -join "`r`n")
"@
    Set-Content -LiteralPath $CfgPath -Value $CfgContent -Encoding UTF8
    Write-Host "Wrote config.yml -> $CfgPath"
}
