# Migrate a DeskSense Node

This workflow moves one existing DeskSense Node from an old Windows PC to a new Windows PC. It preserves the node's bearer token and Cloudflare Named Tunnel credentials so the public endpoint can remain unchanged.

## Export on the old PC

From the project root:

```powershell
.\scripts\export-move.ps1
```

The script creates `dist\desksense-move-<timestamp>.zip`. The archive contains the project files needed by `install-move.ps1`, `.secrets\API_KEY.txt`, and Cloudflare tunnel credentials/configuration. It does not include focus-history databases.

## Handle the archive securely

The MOVE ZIP contains sensitive credentials:

- Bearer Token (`.secrets\API_KEY.txt`)
- Cloudflare tunnel credentials JSON and configuration

Treat it like a password file. Do not commit it to GitHub, upload it to a public cloud drive, or share a public link. Transfer it through a private channel, delete it after migration, and remove any temporary copies.

## Install on the new PC

Extract the archive into a private directory, open PowerShell in its `project` directory, and run:

```powershell
.\scripts\install-move.ps1
```

The script discovers the extracted root and current user profile, restores the token and tunnel files, creates the virtual environment, rewrites `~\.cloudflared\config.yml` for the new paths, registers Interactive AtLogOn tasks, and starts the server and Named Tunnel. It asks for an exact `YES` confirmation after warning that the old PC must be stopped first.

## Verify and clean up

```powershell
Invoke-WebRequest http://127.0.0.1:8765/healthz
.\scripts\status.ps1
```

Confirm the public MCP URL and all seven tools from the new PC. Stop the old node before starting the same Named Tunnel, then delete the MOVE ZIP and any extracted credential copies once the migration is verified.
