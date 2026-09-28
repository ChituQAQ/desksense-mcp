# Migrate a DeskSense Node

This workflow moves one existing DeskSense Node from an old Windows PC to a new Windows PC. It preserves the node's bearer token and the Cloudflare Named Tunnel credential so the public endpoint can remain unchanged.

## Export on the old PC

From the project root:

```powershell
.\scripts\export-move.ps1
```

The script creates `dist\desksense-move-<timestamp>.zip`. It exports the minimum sensitive set:

- the **single** tunnel credential JSON referenced by `~\.cloudflared\config.yml` (verified against the `tunnel:` id in that file);
- the DeskSense route fragment: ingress entries from `config.yml` that point at the project's local port (from `config.json`), recorded in `manifest.json`;
- `.secrets\API_KEY.txt` and the project files needed by `install-move.ps1`.

It refuses to run when `config.yml` is missing, when the credential's `TunnelID` does not match the configured tunnel, or when no ingress route points at the local port. It never packs other tunnels' credentials from `~\.cloudflared`, and never ships the full shared `config.yml` with unrelated business routes. Focus-history databases are not included.

## Handle the archive securely

The MOVE ZIP contains sensitive credentials:

- Bearer Token (`.secrets\API_KEY.txt`)
- Cloudflare tunnel credentials JSON (`cloudflared\<tunnel-id>.json`)

Treat it like a password file. Do not commit it to GitHub, upload it to a public cloud drive, or share a public link. Transfer it through a private channel, delete it after migration, and remove any temporary copies.

## Install on the new PC

Extract the archive into a private directory, open PowerShell in its `project` directory, and run:

```powershell
.\scripts\install-move.ps1
```

Optional flag:

```powershell
.\scripts\install-move.ps1 -MergeIngress
```

Behavior:

- The tunnel credential is restored by the exact tunnel id in `manifest.json` — never "the last JSON found". A credential whose `TunnelID` does not match the manifest aborts the install before anything is written.
- If `~\.cloudflared\config.yml` **does not exist**, it is written fresh from the manifest routes plus the `http_status:404` catch-all.
- If `~\.cloudflared\config.yml` **exists for a different tunnel**, the install aborts: one `config.yml` serves exactly one tunnel, and the script never rewrites another tunnel's configuration. Run the two tunnels with separate `--config` files instead.
- If it exists for the **same tunnel**, the install refuses by default. With `-MergeIngress`, only routes whose hostname is missing are appended before the catch-all; existing lines are left byte-for-byte untouched.
- Archives produced by older exports (manifest without `routes`) fall back to the first route in the archived `config.yml`, with a warning.

The script discovers the extracted root and current user profile, restores the token and tunnel files, creates the virtual environment, reuses the project's hardened autostart chain (`install-autostart.ps1`, `install-tunnel-autostart.ps1`, `start.ps1`), and starts the server and Named Tunnel. It asks for an exact `YES` confirmation after warning that the old PC must be stopped first.

## Verify and clean up

```powershell
Invoke-WebRequest http://127.0.0.1:<port>/healthz
.\scripts\status.ps1
```

The local port comes from the migrated `config.json`. Confirm the public MCP URL and all seven tools from the new PC. Stop the old node before starting the same Named Tunnel, then delete the MOVE ZIP and any extracted credential copies once the migration is verified.
