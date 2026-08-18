# DeskSense — Cloudflare Quick Tunnel 启动脚本
# 临时公网地址（用于测试），需已安装 cloudflared 或从 pip 获得 cloudflared。
# 用法: .\scripts\start-quick-tunnel.ps1
$ErrorActionPreference = 'Stop'

# 查找 cloudflared
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) {
    $pipCf = Join-Path $env:LOCALAPPDATA 'pip\Scripts\cloudflared.exe'
    if (Test-Path $pipCf) { $cf = $pipCf }
}
if (-not $cf) {
    Write-Host "未找到 cloudflared。请先安装："
    Write-Host "  winget install --id Cloudflare.cloudflared"
    Write-Host "  或  pip install cloudflared"
    exit 1
}

$Root = Split-Path -Parent $PSScriptRoot
$Port = 8765
$ConfigPath = Join-Path $Root 'config.json'
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    $Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Config.port) { $Port = [int]$Config.port }
}
Write-Host "正在启动 Quick Tunnel -> http://127.0.0.1:$Port/mcp"
Write-Host "按 Ctrl+C 停止。"

# 隧道进程在前台运行，方便查看分配到的 trycloudflare.com 地址
& $cf tunnel --url "http://127.0.0.1:$Port"
