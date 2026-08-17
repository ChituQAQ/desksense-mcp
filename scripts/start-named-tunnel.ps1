# Cloudflared Named Tunnel "pc-sense-mcp" autostart script (Task Scheduler)
# Register:  powershell -ExecutionPolicy Bypass -File scripts/install-tunnel-autostart.ps1
# Idempotent: exits if tunnel is already running (metrics port 20242 occupied).
$ErrorActionPreference = 'Stop'

$Cf = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$Cfg = 'C:\Users\Administrator\.cloudflared\config.yml'
$Log = 'C:\Users\Administrator\.cloudflared\tunnel.log'

if (-not (Test-Path $Cf)) { throw "cloudflared not found: $Cf" }
if (-not (Test-Path $Cfg)) { throw "config not found: $Cfg" }

# Idempotency check: is metrics port 20242 already in use?
$already = Get-NetTCPConnection -LocalPort 20242 -State Listen -ErrorAction SilentlyContinue
if ($already) {
    Write-Host "Cloudflared named tunnel already running (PID $($already.OwningProcess))"
    exit 0
}

Start-Process -FilePath $Cf -ArgumentList @('tunnel','--config',$Cfg,'run','pc-sense-mcp') `
    -WindowStyle Hidden -RedirectStandardOutput $Log -RedirectStandardError "$Log.err"
Start-Sleep -Seconds 4
Write-Host "Cloudflared named tunnel (pc-sense-mcp) started."
Write-Host "Public URL: https://pc.sullyos.ccwu.cc"