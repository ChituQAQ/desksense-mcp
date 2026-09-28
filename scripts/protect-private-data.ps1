# Restrict private data to the current user, SYSTEM, and local Administrators.
[CmdletBinding()]
param([string]$Root = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath($Root)
$CurrentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$AllowedSids = @($CurrentSid.Value, 'S-1-5-18', 'S-1-5-32-544') | Select-Object -Unique

function Assert-NotReparsePoint {
    param([System.IO.FileSystemInfo]$Item)
    if ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to change permissions through a reparse point: $($Item.FullName)"
    }
}

# Reject redirected ancestors as well as entries inside the private directories.
$Ancestor = Get-Item -LiteralPath $Root -Force
while ($null -ne $Ancestor) {
    Assert-NotReparsePoint $Ancestor
    $Ancestor = $Ancestor.Parent
}
$Targets = New-Object 'System.Collections.Generic.List[System.IO.FileSystemInfo]'
foreach ($Name in @('.secrets', 'data')) {
    $Path = Join-Path $Root $Name
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
    $Directory = Get-Item -LiteralPath $Path -Force
    Assert-NotReparsePoint $Directory
    if (-not $Directory.PSIsContainer) { throw "Not a directory: $Path" }
    $Pending = New-Object 'System.Collections.Generic.Stack[System.IO.FileSystemInfo]'
    $Pending.Push($Directory)
    while ($Pending.Count -gt 0) {
        $Item = $Pending.Pop()
        Assert-NotReparsePoint $Item
        $Targets.Add($Item)
        if ($Item.PSIsContainer) {
            foreach ($Child in @(Get-ChildItem -LiteralPath $Item.FullName -Force)) {
                $Pending.Push($Child)
            }
        }
    }
}

# Preflight the entire tree before changing any ACL. Protected children also lose
# old explicit grants; new files will inherit only the private directory's grants.
foreach ($Item in $Targets) {
    $Acl = Get-Acl -LiteralPath $Item.FullName
    $Acl.SetAccessRuleProtection($true, $false)
    foreach ($Rule in @($Acl.Access)) { $Acl.RemoveAccessRuleSpecific($Rule) }
    $Inheritance = [System.Security.AccessControl.InheritanceFlags]::None
    if ($Item.PSIsContainer) {
        $Inheritance = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    }
    foreach ($SidValue in $AllowedSids) {
        $Sid = New-Object System.Security.Principal.SecurityIdentifier($SidValue)
        $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $Sid, [System.Security.AccessControl.FileSystemRights]::FullControl,
            $Inheritance, [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $Acl.AddAccessRule($Rule)
    }
    Set-Acl -LiteralPath $Item.FullName -AclObject $Acl
}
Write-Host 'Private data ACLs restricted to the current user, SYSTEM, and Administrators.'
