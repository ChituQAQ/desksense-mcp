[CmdletBinding()]
param(
    [string]$Hostname,
    [string]$TunnelName,
    [string]$AllowedOrigin,
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [switch]$NoAutostart
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$TaskMcp = 'DeskSense MCP'
$TaskTunnel = 'Cloudflared Named Tunnel'
$TemporaryServer = $null
$TemporaryTunnel = $null
$TemporaryFiles = @()
$InstallSucceeded = $false

if ($env:OS -ne 'Windows_NT') {
    throw 'DeskSense installation is supported only on Windows.'
}

$HasHostname = -not [string]::IsNullOrWhiteSpace($Hostname)
$HasTunnelName = -not [string]::IsNullOrWhiteSpace($TunnelName)
if ($HasHostname -xor $HasTunnelName) {
    throw 'Hostname and TunnelName must be provided together.'
}
$NamedMode = $HasHostname -and $HasTunnelName

function Get-NormalizedOrigin {
    param([string]$Value)

    $Parsed = $null
    if (-not [Uri]::TryCreate($Value, [UriKind]::Absolute, [ref]$Parsed)) {
        throw "AllowedOrigin must be an absolute http:// or https:// origin: $Value"
    }
    if ($Parsed.Scheme -notin @('http', 'https') -or -not $Parsed.Host) {
        throw "AllowedOrigin must be an absolute http:// or https:// origin: $Value"
    }
    if ($Parsed.AbsolutePath -ne '/' -or $Parsed.Query -or $Parsed.Fragment -or $Parsed.UserInfo) {
        throw "AllowedOrigin must not contain credentials, a path, query, or fragment: $Value"
    }
    return $Parsed.GetLeftPart([UriPartial]::Authority)
}

if ($NamedMode) {
    $Hostname = $Hostname.Trim().ToLowerInvariant()
    $TunnelName = $TunnelName.Trim()
    if ($Hostname.Contains('://') -or $Hostname.Contains('/') -or $Hostname.Contains(':')) {
        throw 'Hostname must be a DNS hostname without a scheme, path, or port.'
    }
    if ([Uri]::CheckHostName($Hostname) -ne [UriHostNameType]::Dns) {
        throw 'Hostname must be a valid DNS hostname.'
    }
}
if (-not [string]::IsNullOrWhiteSpace($AllowedOrigin)) {
    $AllowedOrigin = Get-NormalizedOrigin $AllowedOrigin.Trim()
} else {
    $AllowedOrigin = $null
}

$Root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$ConfigPath = Join-Path $Root 'config.json'
$SecretsDir = Join-Path $Root '.secrets'
$ApiKeyPath = Join-Path $SecretsDir 'API_KEY.txt'
$DataDir = Join-Path $Root 'data'
$DatabasePath = Join-Path $DataDir 'pc_sense.db'
$LogsDir = Join-Path $Root 'logs'
$VenvDir = Join-Path $Root '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VerifierPath = Join-Path $Root 'scripts\verify-install.py'
$LocalOrigin = "http://127.0.0.1:$Port"
$LocalBrowserOrigin = "http://localhost:$Port"
$PublicOrigin = $null
$CorsTestOrigin = $LocalBrowserOrigin
$AllowedOrigins = @()

if ($NamedMode) {
    $PublicOrigin = "https://$Hostname"
    $AllowedOrigins = @($PublicOrigin)
    if ($AllowedOrigin -and $AllowedOrigins -notcontains $AllowedOrigin) {
        $AllowedOrigins += $AllowedOrigin
    }
    $CorsTestOrigin = if ($AllowedOrigin) { $AllowedOrigin } else { $PublicOrigin }
} elseif ($AllowedOrigin) {
    $AllowedOrigins = @($AllowedOrigin)
    $CorsTestOrigin = $AllowedOrigin
}

if (-not (Test-Path -LiteralPath $VerifierPath -PathType Leaf)) {
    throw "Installer verifier is missing: $VerifierPath"
}

function Find-SupportedPython {
    $Candidates = @()
    $Launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($Launcher) {
        foreach ($Minor in @(14, 13, 12, 11)) {
            $Candidates += [pscustomobject]@{
                Exe = $Launcher.Source
                Prefix = @("-3.$Minor")
            }
        }
    }
    $Python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($Python) {
        $Candidates += [pscustomobject]@{ Exe = $Python.Source; Prefix = @() }
    }

    foreach ($Candidate in $Candidates) {
        $VersionText = (& $Candidate.Exe @($Candidate.Prefix) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $VersionText) { continue }
        $Parts = $VersionText.Trim().Split('.')
        if ($Parts.Count -eq 2 -and [int]$Parts[0] -eq 3 -and
            [int]$Parts[1] -ge 11 -and [int]$Parts[1] -le 14) {
            return [pscustomobject]@{
                Exe = $Candidate.Exe
                Prefix = @($Candidate.Prefix)
                Version = $VersionText.Trim()
            }
        }
    }
    throw 'Python 3.11, 3.12, 3.13, or 3.14 was not found on PATH.'
}

function ConvertTo-ProcessArgument {
    param([string]$Value)
    if ($Value -notmatch '[\s"]') { return $Value }
    $Escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $Escaped = [regex]::Replace($Escaped, '(\\+)$', '$1$1')
    return '"' + $Escaped + '"'
}

function Start-NativeProcess {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )
    $StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $StartInfo.FileName = $FilePath
    $StartInfo.Arguments = (($ArgumentList | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join ' ')
    $StartInfo.WorkingDirectory = $WorkingDirectory
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $StartInfo
    if (-not $Process.Start()) {
        $Process.Dispose()
        throw "Process did not start: $FilePath"
    }
    return $Process
}

function Invoke-CapturedProcess {
    param([string]$FilePath, [string[]]$ArgumentList)
    $StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $StartInfo.FileName = $FilePath
    $StartInfo.Arguments = (($ArgumentList | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join ' ')
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $StartInfo
    try {
        if (-not $Process.Start()) { throw "Process did not start: $FilePath" }
        $OutputTask = $Process.StandardOutput.ReadToEndAsync()
        $ErrorTask = $Process.StandardError.ReadToEndAsync()
        $Process.WaitForExit()
        return [pscustomobject]@{
            ExitCode = $Process.ExitCode
            StandardOutput = $OutputTask.Result
            StandardError = $ErrorTask.Result
        }
    } finally {
        $Process.Dispose()
    }
}

function Get-PortListener {
    return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Stop-TemporaryProcess {
    param([object]$Process)
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            $Process.WaitForExit(10000) | Out-Null
        }
    } finally {
        $Process.Dispose()
    }
}

try {
    $PythonInfo = Find-SupportedPython
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        & $PythonInfo.Exe @($PythonInfo.Prefix) -m venv $VenvDir
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
            throw 'Virtual environment creation failed.'
        }
    }
    $VenvVersion = (& $VenvPython -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
    $VenvParts = $VenvVersion.Split('.')
    if ($LASTEXITCODE -ne 0 -or $VenvParts.Count -ne 2 -or
        [int]$VenvParts[0] -ne 3 -or [int]$VenvParts[1] -lt 11 -or
        [int]$VenvParts[1] -gt 14) {
        throw "Existing virtual environment uses unsupported Python $VenvVersion."
    }

    & $VenvPython -m pip install --disable-pip-version-check --quiet -r (Join-Path $Root 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $VenvPython -m pip install --disable-pip-version-check --quiet -e $Root
    if ($LASTEXITCODE -ne 0) { throw 'Editable project installation failed.' }

    if ($NamedMode) {
        $NodeConfigured = $false
        if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
            try {
                $ExistingConfig = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $NodeConfigured = @($ExistingConfig.allowed_origins) -contains $PublicOrigin
            } catch {
                throw "Existing config is not valid UTF-8 JSON: $ConfigPath"
            }
        }
        if ((Test-Path -LiteralPath $ApiKeyPath -PathType Leaf) -and -not $NodeConfigured) {
            throw "An existing token is not identified as a deployment for '$Hostname'."
        }
        if ((Test-Path -LiteralPath $DatabasePath -PathType Leaf) -and -not $NodeConfigured) {
            throw "An existing database is not identified as a deployment for '$Hostname'."
        }
    }

    New-Item -ItemType Directory -Force -Path $SecretsDir, $DataDir, $LogsDir | Out-Null
    $BootstrapArgs = @('-m', 'desksense.bootstrap', '--root', $Root, '--port', [string]$Port)
    foreach ($Origin in $AllowedOrigins) {
        $BootstrapArgs += @('--allowed-origin', $Origin)
    }
    $BootstrapResult = (& $VenvPython @BootstrapArgs).Trim()
    if ($LASTEXITCODE -ne 0 -or $BootstrapResult -notin @('created', 'retained')) {
        throw 'Token/config bootstrap failed.'
    }

    $Cloudflared = $null
    $CloudflaredHome = $null
    $TunnelConfigPath = $null
    $TunnelId = $null

    if ($NamedMode) {
        $UserHome = $env:USERPROFILE
        if (-not $UserHome) {
            $UserHome = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
        }
        if (-not $UserHome) { throw 'Unable to determine the current user home directory.' }
        $CloudflaredHome = Join-Path $UserHome '.cloudflared'
        $TunnelConfigPath = Join-Path $CloudflaredHome "$TunnelName.yml"

        $CloudflaredCommand = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
        if ($CloudflaredCommand) { $Cloudflared = $CloudflaredCommand.Source }
        if (-not $Cloudflared) {
            foreach ($Candidate in @(
                (Join-Path $UserHome '.cloudflared\cloudflared.exe'),
                (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\cloudflared.exe'),
                (Join-Path $env:ProgramFiles 'cloudflared\cloudflared.exe'),
                (Join-Path ${env:ProgramFiles(x86)} 'cloudflared\cloudflared.exe')
            )) {
                if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
                    $Cloudflared = $Candidate
                    break
                }
            }
        }
        if (-not $Cloudflared) {
            throw 'cloudflared.exe is required only for Named Tunnel mode and was not found.'
        }
        New-Item -ItemType Directory -Force -Path $CloudflaredHome | Out-Null

        function Read-TunnelList {
            $Command = Invoke-CapturedProcess $Cloudflared @('tunnel', 'list', '--output', 'json')
            if ($Command.ExitCode -ne 0) {
                return [pscustomobject]@{ Success = $false; Tunnels = @() }
            }
            try {
                $Parsed = $Command.StandardOutput.Trim() | ConvertFrom-Json
                return [pscustomobject]@{ Success = $true; Tunnels = @($Parsed) }
            } catch {
                return [pscustomobject]@{ Success = $false; Tunnels = @() }
            }
        }

        $TunnelListResult = Read-TunnelList
        if (-not $TunnelListResult.Success) {
            Write-Host 'Complete Cloudflare authorization in the browser, then return here.'
            $LoginCommand = Invoke-CapturedProcess $Cloudflared @('tunnel', 'login')
            if ($LoginCommand.ExitCode -ne 0) {
                throw 'Cloudflare browser authorization did not complete successfully.'
            }
            $TunnelListResult = Read-TunnelList
            if (-not $TunnelListResult.Success) { throw 'Cloudflare login could not be validated.' }
        }

        $MatchingTunnels = @($TunnelListResult.Tunnels | Where-Object { $_.name -eq $TunnelName })
        if ($MatchingTunnels.Count -gt 1) { throw "More than one tunnel is named '$TunnelName'." }
        if ($MatchingTunnels.Count -eq 0) {
            $CreateCommand = Invoke-CapturedProcess $Cloudflared @('tunnel', 'create', $TunnelName)
            if ($CreateCommand.ExitCode -ne 0) { throw "Failed to create Named Tunnel '$TunnelName'." }
            $TunnelListResult = Read-TunnelList
            if (-not $TunnelListResult.Success) { throw 'Unable to read the tunnel list after creation.' }
            $MatchingTunnels = @($TunnelListResult.Tunnels | Where-Object { $_.name -eq $TunnelName })
            if ($MatchingTunnels.Count -ne 1) {
                throw 'The newly created tunnel could not be identified uniquely.'
            }
        }

        $TunnelId = [string]$MatchingTunnels[0].id
        if (-not $TunnelId) { throw 'The tunnel has no tunnel ID.' }
        $CredentialsPath = Join-Path $CloudflaredHome "$TunnelId.json"
        if (-not (Test-Path -LiteralPath $CredentialsPath -PathType Leaf)) {
            throw "Tunnel credentials are missing: $CredentialsPath"
        }

        $RouteCommand = Invoke-CapturedProcess $Cloudflared @(
            'tunnel', 'route', 'dns', '--overwrite-dns', $TunnelId, $Hostname
        )
        if ($RouteCommand.ExitCode -ne 0) { throw "Failed to route $Hostname to the tunnel." }

        $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        $YamlCredentialsPath = $CredentialsPath.Replace("'", "''")
        $TunnelYaml = @"
tunnel: $TunnelId
credentials-file: '$YamlCredentialsPath'
protocol: http2

ingress:
  - hostname: $Hostname
    service: http://127.0.0.1:$Port
  - service: http_status:404
"@
        [System.IO.File]::WriteAllText($TunnelConfigPath, $TunnelYaml + "`n", $Utf8NoBom)
    }

    if ($NoAutostart) {
        if ((Get-PortListener).Count -gt 0) {
            throw "Port $Port is already in use; refusing to start a temporary verification server."
        }
        $TemporaryServer = Start-NativeProcess $VenvPython @('-m', 'desksense.server') $Root
    } else {
        foreach ($CommandName in @(
            'Register-ScheduledTask', 'New-ScheduledTaskAction',
            'New-ScheduledTaskPrincipal', 'New-ScheduledTaskTrigger'
        )) {
            if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
                throw "Required ScheduledTasks command is unavailable: $CommandName"
            }
        }

        $UserId = if ($env:USERDOMAIN) {
            "$env:USERDOMAIN\$env:USERNAME"
        } else {
            $env:USERNAME
        }
        $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
        $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -MultipleInstances IgnoreNew
        $Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive `
            -RunLevel Limited

        function Register-InteractiveTask {
            param([string]$Name, [object]$Action, [string]$Description)
            Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
            Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger `
                -Settings $Settings -Principal $Principal -Description $Description | Out-Null
        }

        $Wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
        $McpLauncher = Join-Path $PSScriptRoot 'run-desksense-hidden.vbs'
        if (-not (Test-Path -LiteralPath $Wscript -PathType Leaf)) {
            throw "wscript.exe was not found: $Wscript"
        }
        if (-not (Test-Path -LiteralPath $McpLauncher -PathType Leaf)) {
            throw "MCP launcher was not found: $McpLauncher"
        }
        $McpArguments = "//B //NoLogo `"$McpLauncher`" `"$VenvPython`" `"$Root`""
        $McpAction = New-ScheduledTaskAction -Execute $Wscript -Argument $McpArguments `
            -WorkingDirectory $Root
        Register-InteractiveTask $TaskMcp $McpAction 'DeskSense MCP user-login autostart'

        if ($NamedMode) {
            $TunnelLauncher = Join-Path $PSScriptRoot 'run-cloudflared-hidden.vbs'
            if (-not (Test-Path -LiteralPath $TunnelLauncher -PathType Leaf)) {
                throw "Tunnel launcher was not found: $TunnelLauncher"
            }
            $TunnelArguments = "//B //NoLogo `"$TunnelLauncher`" `"$Cloudflared`" `"$TunnelConfigPath`" `"$TunnelId`""
            $TunnelAction = New-ScheduledTaskAction -Execute $Wscript -Argument $TunnelArguments `
                -WorkingDirectory $Root
            Register-InteractiveTask $TaskTunnel $TunnelAction `
                'Cloudflared Named Tunnel user-login autostart'
        }

        if ((Get-PortListener).Count -eq 0) {
            Start-ScheduledTask -TaskName $TaskMcp
        }
    }

    if ($NamedMode) {
        $MatchingConnectors = @(Get-CimInstance Win32_Process `
            -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.CommandLine -and (
                    $_.CommandLine.Contains($TunnelConfigPath) -or
                    $_.CommandLine.Contains($TunnelId)
                )
            })
        if ($MatchingConnectors.Count -gt 1) {
            throw 'Multiple cloudflared connector processes are running for this tunnel.'
        }
        if ($MatchingConnectors.Count -eq 0) {
            if ($NoAutostart) {
                $TemporaryTunnel = Start-NativeProcess $Cloudflared `
                    @('tunnel', '--config', $TunnelConfigPath, 'run', $TunnelId) $Root
            } else {
                Start-ScheduledTask -TaskName $TaskTunnel
            }
        }
    }

    $VerifyArgs = @(
        $VerifierPath,
        '--local-base', $LocalOrigin,
        '--token-file', $ApiKeyPath,
        '--origin', $CorsTestOrigin,
        '--quiet'
    )
    if ($NamedMode) { $VerifyArgs += @('--public-base', $PublicOrigin) }
    & $VenvPython @VerifyArgs
    if ($LASTEXITCODE -ne 0) { throw 'DeskSense endpoint verification failed.' }
    $InstallSucceeded = $true
} finally {
    Stop-TemporaryProcess $TemporaryTunnel
    Stop-TemporaryProcess $TemporaryServer
    foreach ($TemporaryFile in $TemporaryFiles) {
        if (Test-Path -LiteralPath $TemporaryFile) {
            Remove-Item -LiteralPath $TemporaryFile -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($InstallSucceeded) {
    if ($NamedMode) {
        Write-Host "Named Tunnel MCP URL : $PublicOrigin/mcp"
    } else {
        Write-Host "Local MCP URL        : $LocalOrigin/mcp"
    }
    Write-Host "Token file path      : $ApiKeyPath"
    Write-Host 'Health status        : OK'
    Write-Host 'Tools verification   : 7/7'
}
