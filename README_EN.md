[简体中文](README.md) | [English](README_EN.md)

# DeskSense

DeskSense is a read-only MCP server for Windows. With your authorization, it lets an AI assistant query the current foreground window, open applications, keyboard/mouse idle time, system load, and recent focus history. It does not execute commands, manipulate windows, or remotely control the PC.

Each computer runs an independent DeskSense Node. It exposes MCP Streamable HTTP at `/mcp` and requires bearer-token authentication. A normal local installation does not require Cloudflare. The optional Cloudflare Named Tunnel path is only for users who need a stable public URL.

## Seven MCP tools

DeskSense exposes exactly these seven read-only tools:

- `pc_get_context`: foreground app, idle state, main open apps, and system summary
- `pc_get_focus`: current foreground window and process
- `pc_list_open_apps`: visible desktop application windows
- `pc_get_idle_status`: input idle seconds and active/idle/away state
- `pc_get_pc_status`: CPU, memory, disk, network, and uptime
- `pc_get_top_processes`: processes sorted by CPU or memory
- `pc_get_recent_focus`: recent foreground-window changes

## Data and privacy

DeskSense only reads local state, but responses can contain application names, window titles, process paths, and system metrics. Focus history stays in `data\pc_sense.db`; logs stay under `logs\`. The bearer token is stored only in `.secrets\API_KEY.txt` and is not written to source code or logs.

Do not publish the token or commit `.secrets`, `config.json`, `data`, or `logs`. For public access, use a dedicated Named Tunnel hostname and allow browser origins only for trusted clients.

## Requirements

- Windows 10 or newer
- Python 3.11, 3.12, 3.13, or 3.14 (all covered by Windows CI)
- An MCP client supporting Streamable HTTP and bearer tokens
- A Cloudflare account and `cloudflared` only for Named Tunnel mode

SullyOS is one tested example client; it is neither required nor exclusive.

## Recommended installation: Release ZIP

Regular users do not need Git, pip knowledge, or manual venv, config, token, or Task Scheduler setup.

1. Open [GitHub Releases](https://github.com/ChituQAQ/desksense-mcp/releases).
2. Download `DeskSense-v1.0.1.zip`.
3. Extract it to a stable directory that will not be moved or deleted, such as `C:\Apps\DeskSense`.
4. Open PowerShell in the extracted directory and run one command.

Windows execution policy or the ZIP download mark may block direct `.ps1` execution. This command bypasses the policy only for this PowerShell process and does not change the system policy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

### Default: local installation

The command installs runtime dependencies, creates `.venv`, the token, `config.json`, user-logon autostart, starts the service, and performs a complete MCP verification. The default URL is:

```text
http://127.0.0.1:8765/mcp
```

Local installation does not require Cloudflare, a domain, DNS, `cloudflared`, or a Cloudflare account.

The installer never prints the token; it reports only the token file path. When configuring a client, open `.secrets\API_KEY.txt` locally and use its contents as the bearer token. Do not paste it into logs, issues, or chat messages.

Use `-Port` to select another port from 1 through 65535:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Port 18765
```

### Optional: Cloudflare Named Tunnel

Use this only when you need a stable public HTTPS URL. `-Hostname` and `-TunnelName` must be supplied together:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -Hostname desksense.example.com `
  -TunnelName desksense
```

Only this mode looks for `cloudflared`, opens Cloudflare browser authorization, creates or reuses a Named Tunnel, creates the DNS route, writes ingress using the actual `-Port`, registers tunnel autostart, and verifies the public MCP URL. See the [English installation guide](docs/INSTALL_EN.md) for prerequisites and complete details.

## Connect an MCP client

The client needs two values:

- MCP URL: `http://127.0.0.1:8765/mcp` locally, or `https://desksense.example.com/mcp` with a Named Tunnel
- Authorization: `Bearer <token from .secrets\API_KEY.txt>`

Exact field names depend on the client. It must support MCP Streamable HTTP and a custom Authorization header.

For a browser page connecting directly to DeskSense, CORS checks the page's own origin (scheme, host, and port), not the MCP URL. Local browser origins on `localhost`, `127.0.0.1`, and `::1` are accepted on any port. A remote web page must be configured as an exact origin:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -AllowedOrigin https://client.example.com
```

The same parameter can be added to Named Tunnel installation. Do not set `AllowedOrigin` to `*`.

## Multiple PCs / Node mode

Extract and install one Node separately on each Windows PC. Every Node has its own token, config, data, and logs. Local clients use the URL on that PC. Named Tunnel nodes need distinct hostnames, tunnel names, and tokens.

Moving an existing Node's credentials is a separate sensitive workflow documented in the [migration guide (English)](docs/MIGRATE.md). Do not treat a normal Release ZIP as a credential migration archive.

## Autostart and manual operation

The default installation registers a current-user logon task named `DeskSense MCP`. Its windowless startup chain is:

```text
Task Scheduler -> wscript.exe -> run-desksense-hidden.vbs -> python.exe -m desksense.server
```

Desktop sensing requires the user's interactive session, so the task runs at logon and not as SYSTEM.

Advanced users can pass `-NoAutostart`. The installer still creates the environment, config, and token and completes verification, but then stops the temporary server and leaves no permanent scheduled task. Start it later with `.\scripts\start.ps1`.

## Verification

The installer verifies all of the following:

- `/healthz` returns 200
- unauthenticated `/mcp` returns 401
- the bearer token completes MCP `initialize`
- `tools/list` returns exactly seven tools
- `pc_get_context` succeeds

Manual checks:

```powershell
Invoke-WebRequest http://127.0.0.1:8765/healthz
.\scripts\status.ps1
```

For a custom port, `status.ps1` reads `config.json`.

## Troubleshooting

- Python not found: install a supported 64-bit Python and ensure `py.exe` or `python.exe` is available.
- Script blocked: use the complete `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...` command shown above.
- Port in use: choose an unused port with `-Port`; do not take over another service's port.
- Client gets 401: use `/mcp` and send the token for this Node with the `Bearer` scheme.
- Browser CORS failure: local origins are automatic; configure a remote page with an exact `-AllowedOrigin`, without a page path.
- Named Tunnel failure: confirm the account manages the target DNS zone, `cloudflared` is installed, browser authorization completed, and the hostname is not used elsewhere.
- Logs: inspect `logs\`, but never share `.secrets\`.

## Developer installation

Developers can create an isolated source environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

Regular users should prefer the Release ZIP and installer.

## License

DeskSense is released under the MIT License. See [LICENSE](LICENSE).
