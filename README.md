# DeskSense

DeskSense is a lightweight, read-only Windows MCP server that gives AI assistants awareness of the current PC state.

It exposes MCP Streamable HTTP over a local server, protected by a bearer token. CORS is configurable for browser-based clients. A Cloudflare Tunnel is optional when a node needs controlled public access.

## What is DeskSense

Run one independent DeskSense Node on each Windows PC you want to observe. A node reads desktop and system state; it does not execute commands or modify the computer.

## Features

- Windows-only, read-only PC sensing
- MCP Streamable HTTP endpoint at `/mcp`
- Bearer Token authentication
- Configurable CORS origins
- Optional Cloudflare Named or Quick Tunnel access
- Interactive AtLogOn autostart through Task Scheduler
- Hidden server startup via `wscript.exe`
- Local health endpoint at `/healthz`

## MCP Tools

The server provides exactly these seven read-only tools:

- `pc_get_context`
- `pc_get_focus`
- `pc_list_open_apps`
- `pc_get_idle_status`
- `pc_get_pc_status`
- `pc_get_top_processes`
- `pc_get_recent_focus`

## Architecture

```text
AI assistant / MCP client
          |
          | HTTPS + Bearer Token (optional public tunnel)
          v
Cloudflare Tunnel (optional)
          |
          v
127.0.0.1:8765  ->  python -m desksense.server
          |
          +--> Windows APIs, psutil, and local focus history
```

Each computer has its own token, configuration, runtime data, and optional tunnel. SullyOS is a tested example client, not a required or exclusive client.

## Requirements

- Windows 10 or newer
- Python 3.11 or newer
- `cloudflared` only when using a tunnel
- A compatible MCP client

## Quick Start

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m desksense.server
```

For a complete node installation, including token generation, CORS, tunnel configuration, and autostart tasks:

```powershell
.\scripts\install.ps1 `
  -Hostname desksense.example.com `
  -TunnelName desksense
```

Use `-AllowedOrigin https://example-client.app` when a browser client needs an additional origin. The installer prints the MCP URL and token file path without printing the token.

## Cloudflare Tunnel

Cloudflare is optional. Use a Quick Tunnel for temporary testing:

```powershell
.\scripts\start-quick-tunnel.ps1
```

For a stable hostname, authenticate `cloudflared`, create or select a Named Tunnel, and use `start-named-tunnel.ps1` after installation. Point the tunnel at `http://127.0.0.1:8765` and expose only the intended hostname.

## Connect an MCP Client

Configure the client with:

- MCP URL: `https://desksense.example.com/mcp` (or `http://127.0.0.1:8765/mcp` locally)
- Authentication: `Bearer <token>`

The token is stored locally in `.secrets\API_KEY.txt`. SullyOS can be used as an example client; any MCP client supporting Streamable HTTP and bearer authentication can connect.

## Multiple PCs / Nodes

Install one DeskSense Node per Windows PC. Give every node a distinct hostname, tunnel name, and token, then configure each MCP endpoint separately in the client. Do not copy a node's runtime database or credentials between computers unless using the documented migration workflow.

## Security & Privacy

DeskSense is read-only, but its responses can contain application names, window titles, process information, and system metrics. Keep the bearer token private, restrict `AllowedOrigin` to trusted clients, and place public access behind a properly configured tunnel. Tokens are not written to source code or logs. Focus history is stored locally in `data\pc_sense.db`; logs are written under `logs\`.

## Autostart

The installer registers an Interactive AtLogOn task named `DeskSense MCP`. It launches `wscript.exe`, which starts `run-desksense-hidden.vbs`; the VBS script invokes `python.exe -m desksense.server` with no visible console window.

```powershell
.\scripts\install-autostart.ps1
.\scripts\status.ps1
.\scripts\uninstall-autostart.ps1
```

Interactive logon is intentional because desktop sensing requires the user's Windows session.

## Troubleshooting

- Check local health: `Invoke-WebRequest http://127.0.0.1:8765/healthz`
- Check task and process state: `.\scripts\status.ps1`
- Review files under `logs\` (never share `.secrets\`)
- Confirm `PYTHONPATH=src` when running directly from a checkout
- Confirm the client sends `Authorization: Bearer <token>` and uses `/mcp`
- For tunnel problems, verify `cloudflared` login, hostname routing, and that only one node runs a Named Tunnel

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Source is under `src/desksense`; tests are under `tests`. The server can be run locally with `PYTHONPATH=src` as shown above.

## License

DeskSense is released under the MIT License. See [LICENSE](LICENSE).
