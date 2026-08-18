# DeskSense ADD Home PC

This ADD workflow creates a second, independent DeskSense deployment. It does not move, stop, or modify the existing Work PC deployment at `https://<your-existing-hostname>/mcp`.

On the Home PC, obtain this repository and run from the project root:

```powershell
.\scripts\install-add.ps1 `
  -Hostname <your-second-node-hostname> `
  -TunnelName pc-sense-home
```

The script checks Windows, Python 3.11+, and `cloudflared`; creates `.venv`; installs dependencies; generates a new bearer token; writes the Home config; creates or reuses only the `pc-sense-home` Named Tunnel; routes only `<your-second-node-hostname>`; writes `~/.cloudflared/pc-sense-home.yml`; installs two interactive-user logon tasks; starts one server and one connector; then verifies local/public health, authentication, all seven tools, `pc_get_context`, and SullyOS CORS headers.

If Cloudflare login is not already valid, the script pauses at `cloudflared tunnel login`. Complete the browser authorization and return to the terminal. Do not copy a certificate, credentials JSON, API token, or Work PC tunnel credentials.

The Home bearer token is stored at `.secrets\API_KEY.txt`. The script never displays it. A rerun preserves a valid existing Home token and replaces the same two scheduled tasks instead of creating duplicates. If an existing token or database is not paired with the Home configuration, installation stops rather than reusing or overwriting it.

Configure SullyOS with:

- MCP URL: `https://<your-second-node-hostname>/mcp`
- Authentication: Bearer token from `.secrets\API_KEY.txt` on the Home PC

The SullyOS origin remains `<your-mcp-client-origin>`; wildcard CORS and disabled DNS rebinding protection are not used.
