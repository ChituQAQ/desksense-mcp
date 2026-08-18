# Install a DeskSense Node

This is the normal first-install workflow for one Windows PC. A DeskSense Node is an independent read-only MCP server deployment for that computer.

## Prerequisites

- Windows 10 or newer
- Python 3.11+ on `PATH`
- `cloudflared` installed and authenticated for a Named Tunnel

From the repository root, run:

```powershell
.\scripts\install.ps1 `
  -Hostname desksense.example.com `
  -TunnelName desksense
```

Optional browser-client CORS origin:

```powershell
.\scripts\install.ps1 `
  -Hostname desksense.example.com `
  -TunnelName desksense `
  -AllowedOrigin https://example-client.app
```

## Parameters

- `Hostname`: public DNS hostname routed to this node, without `https://`.
- `TunnelName`: Cloudflare Named Tunnel name to create or reuse.
- `AllowedOrigin`: optional additional browser origin. The hostname origin is always allowed.

The installer creates `.venv`, installs dependencies, writes `config.json`, and generates `.secrets\API_KEY.txt` when no token exists. Treat that file as a password. Runtime focus history remains in `data\pc_sense.db`; logs remain in `logs\`.

## What installation configures

- Local server: `http://127.0.0.1:8765`
- MCP URL: `https://<Hostname>/mcp`
- Health URL: `http://127.0.0.1:8765/healthz`
- Interactive `AtLogOn` task named `DeskSense MCP`
- Hidden startup chain: Task Scheduler -> `wscript.exe` -> `run-desksense-hidden.vbs` -> `python.exe -m desksense.server`

## Verify the node

```powershell
Invoke-WebRequest http://127.0.0.1:8765/healthz
.\scripts\status.ps1
```

Connect an MCP client with `https://<Hostname>/mcp` and the bearer token from `.secrets\API_KEY.txt`. After initialization, `tools/list` must contain exactly the seven `pc_get_*` tools documented in the README.
