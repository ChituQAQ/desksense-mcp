# DeskSense — 状态脚本
# 用法: .\scripts\status.ps1
$Root = Split-Path -Parent $PSScriptRoot
$Port = 8765
$ConfigPath = Join-Path $Root 'config.json'
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    try {
        $Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($Config.port) { $Port = [int]$Config.port }
    } catch {
        Write-Host "状态: UNKNOWN (config.json 无法解析)"
        exit 1
    }
}
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    $procPid = $conns.OwningProcess | Select-Object -First 1
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 5
        if (-not $r.ok -or $r.service -ne 'DeskSense MCP') {
            throw 'healthz response is not DeskSense MCP'
        }
        Write-Host "状态: RUNNING (PID=$procPid)"
        Write-Host ("healthz: " + ($r | ConvertTo-Json -Compress))
        Write-Host "MCP URL: http://127.0.0.1:$Port/mcp"
    } catch {
        Write-Host "状态: LISTENER_PRESENT (PID=$procPid, 未验证为 DeskSense)"
        Write-Host "healthz: 验证失败 ($($_.Exception.Message))"
        exit 1
    }
} else {
    Write-Host "状态: STOPPED"
}
