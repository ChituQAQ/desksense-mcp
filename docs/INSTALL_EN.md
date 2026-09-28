[简体中文](INSTALL.md) | [English](INSTALL_EN.md)

# Install a DeskSense Node

This guide is for a Windows user installing DeskSense for the first time. The recommended source is the GitHub Release ZIP. A normal local installation does not require Cloudflare.

## Preparation

Every mode requires:

- Windows 10 or newer
- Python 3.11, 3.12, 3.13, or 3.14
- `DeskSense-v1.0.1.zip` extracted to a stable directory

Open PowerShell in the extracted directory. The commands use `-ExecutionPolicy Bypass` only for the current process; they do not change the system execution policy.

## Mode 1: local-only installation (default)

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

This does not require a Cloudflare account, domain, DNS, `cloudflared`, or tunnel credentials.

The installer:

1. Checks Windows and a supported Python version.
2. Creates `.venv`, installs runtime dependencies, and runs `pip install -e .`.
3. Creates `.secrets\API_KEY.txt`; it generates a 64-hex token when missing and preserves an existing valid token.
4. Creates or updates `config.json`, binding to `127.0.0.1:8765` by default.
5. Registers the current-user logon task `DeskSense MCP`, using `wscript.exe` and VBS for windowless startup.
6. Starts the service and verifies health, 401 behavior, MCP initialize, exactly seven tools, and `pc_get_context`.

After success, use:

```text
MCP URL: http://127.0.0.1:8765/mcp
Token:   .secrets\API_KEY.txt
```

The installer prints only the token file path, never its contents.

### Custom port

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Port 18765
```

The port must be from 1 through 65535 and must be unused.

### No permanent autostart

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -Port 18765 `
  -NoAutostart
```

This still creates the environment, config, and token and performs end-to-end verification. It starts a temporary server and then stops that exact PID. It creates no permanent task and leaves no background process. Start manually later with `.\scripts\start.ps1`.

### Browser-client origin

Local page origins on `http://localhost:<any port>`, `http://127.0.0.1:<any port>`, and `http://[::1]:<any port>` are allowed automatically. Configure a remote page as an exact origin:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -AllowedOrigin https://client.example.com
```

`AllowedOrigin` is the page's scheme, host, and optional port. It cannot contain a path, query, credentials, or fragment. Do not use `*`.

## Mode 2: Cloudflare Named Tunnel (optional)

Choose this only when you need a stable public HTTPS URL.

Additional prerequisites:

- A Cloudflare account
- An installed, runnable `cloudflared`
- A domain and DNS zone managed by that Cloudflare account
- The ability to complete Cloudflare authorization in a browser
- An available hostname such as `desksense.example.com`

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -Hostname desksense.example.com `
  -TunnelName desksense
```

Both parameters are required together. Supplying only one fails before any installation operation.

After local bootstrap, Named Tunnel mode:

1. Locates `cloudflared`.
2. Validates login and opens browser authorization when required.
3. Creates or reuses the named tunnel.
4. Confirms that tunnel's credentials JSON exists.
5. Creates or updates the DNS route for the hostname.
6. Writes `~\.cloudflared\<TunnelName>.yml` with ingress pointing to the actual `127.0.0.1:<Port>`.
7. Registers `DeskSense MCP` and `Cloudflared Named Tunnel` current-user logon tasks.
8. Verifies both local and public MCP endpoints.

The resulting MCP URL is:

```text
https://desksense.example.com/mcp
```

You can add `-AllowedOrigin https://client.example.com`. The public hostname origin is also added to the exact allowlist.

`-NoAutostart` also applies here: the installer temporarily starts the local server and required tunnel connector, then stops only the temporary processes it created and registers no permanent tasks.

## Autostart structure

Local server:

```text
Task Scheduler (AtLogOn, current interactive user)
  -> wscript.exe
  -> scripts\run-desksense-hidden.vbs
  -> powershell.exe -File scripts\start.ps1 -Wait
  -> .venv\Scripts\python.exe -m desksense.server
```

Named Tunnel also registers:

```text
Task Scheduler (AtLogOn, current interactive user)
  -> wscript.exe
  -> scripts\run-cloudflared-hidden.vbs
  -> cloudflared tunnel --config <config> run <tunnel-id>
```

## Connect and verify

The MCP client must send:

- A Streamable HTTP URL ending in `/mcp`
- `Authorization: Bearer <token>`

Manual health checks:

```powershell
Invoke-WebRequest http://127.0.0.1:8765/healthz
.\scripts\status.ps1
```

For a custom port, `status.ps1` reads `config.json`.

## Remove autostart

`.\scripts\uninstall-autostart.ps1` handles only the local DeskSense service task. Manage a Named Tunnel task separately and deliberately to avoid interrupting another node using that tunnel.

## Security

- `.secrets\API_KEY.txt` is a password.
- Before creating a token, the installer restricts Windows ACLs on `.secrets` and `data` to the current user, SYSTEM, and local Administrators. Reparse points are rejected. Existing source installs can run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\protect-private-data.ps1` separately. This does not isolate the app from administrators or malicious users who can modify its program directory; use a trusted installation directory.
- A Cloudflare credentials JSON file is a tunnel key.
- Never upload, commit, or share either file.
- Never run the same Named Tunnel credentials on two PCs at once.
- DeskSense tools are read-only, but window titles and process details are still private data.

For an existing Node credential move, see the [migration guide (English)](MIGRATE.md).
