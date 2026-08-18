# DeskSense — 状态脚本
# 用法: .\scripts\status.ps1
$conns = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    $procPid = $conns.OwningProcess | Select-Object -First 1
    Write-Host "状态: RUNNING (PID=$procPid)"
    try {
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/healthz' -TimeoutSec 5
        Write-Host ("healthz: " + ($r | ConvertTo-Json -Compress))
    } catch {
        Write-Host "healthz: 无法访问 ($($_.Exception.Message))"
    }
    Write-Host "MCP URL: http://127.0.0.1:8765/mcp"
} else {
    Write-Host "状态: STOPPED"
}