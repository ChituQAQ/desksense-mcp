# Migrate a DeskSense Node

This workflow moves one existing DeskSense Node from an old Windows PC to a new Windows PC. It preserves the node's bearer token and the Cloudflare Named Tunnel credential so the public endpoint can remain unchanged.

## Export on the old PC

MOVE uses the Node's `.venv` Python (or `python.exe` on PATH) and the explicit PyYAML dependency. If updating an older Node's scripts, first update its dependencies; the export script never installs packages automatically:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\scripts\export-move.ps1
```

The exporter scans `~\.cloudflared\*.yml` and `*.yaml` for the **unique** configuration whose ingress targets this Node's local port from `config.json`. This includes both the installer's `<TunnelName>.yml` and legacy `config.yml`. Multiple matches, no matches, or unparseable candidates are not guessed. Select a known configuration explicitly when necessary:

```powershell
.\scripts\export-move.ps1 -ConfigPath "$env:USERPROFILE\.cloudflared\desksense.yml"
```

The script creates `dist\desksense-move-<timestamp>.zip`. It exports the minimum sensitive set:

- the **single** credential JSON referenced by the selected config, verified against its `tunnel:` ID. Single/double-quoted absolute paths and credentials outside `~\.cloudflared` are supported; only the file's safe basename is used inside the archive;
- complete selected ingress entries, including `path` and per-route `originRequest`, in `manifest.json.routes`; top-level `originRequest` is stored separately in `origin_request_defaults`;
- `.secrets\API_KEY.txt` and the project files needed by `install-move.ps1`.

A mismatched credential `TunnelID` aborts export. Other credentials, unrelated routes and focus-history databases are never included; the complete shared config is not shipped. Route settings are not printed to the console.

Safety limits: relative credential paths are refused because a connector's working directory is ambiguous (use an absolute path). YAML duplicate/merge keys, anchors/aliases, unsafe tags and non-JSON values are refused rather than silently transformed. `originRequest.caPool` references an external machine-local file and requires a separate, explicit migration instead of being copied or silently broken. Credential basenames must contain only ASCII letters, digits, underscores, hyphens and dots, ending in `.json`.

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

- The tunnel credential is restored by the exact tunnel ID in `manifest.json` — never "the last JSON found". Credential/config validation finishes before the restore helper writes any tunnel files (the installer may already have created the venv and restored the API token).
- If `~\.cloudflared\config.yml` **does not exist**, it is written fresh from the complete manifest routes, source origin defaults, and a final `http_status:404` catch-all.
- If it **exists for a different tunnel**, restore aborts. Run the two tunnels with separate `--config` files instead of overwriting the existing config.
- If it exists for the **same tunnel**, restore refuses by default. With `-MergeIngress`, missing hostnames are inserted before the final catch-all, including an HTTP/HTTPS service catch-all. Existing bytes (comments, BOM, line endings, routes and unrelated settings) are preserved. Identical routes are idempotent; conflicting routes for an existing hostname, different source/target origin defaults, or earlier wildcard/path rules that could shadow the new hostname cause refusal instead of a silent routing change.
- Missing/misplaced catch-alls and malformed YAML are rejected. A flow-style ingress list or a catch-all layout that cannot be safely spliced must be expanded to a conventional block list before merging.
- Older manifests without `routes` retain the warning-based fallback to the first archived hostname route, now including that route's options and source origin defaults. Manifests without `origin_request_defaults` mean no source defaults.

The helper checks the entire candidate YAML and its ingress semantics before writing and atomically replaces the config file. `install-move.ps1` also supplies its discovered cloudflared executable for **offline** `tunnel ingress validate` before any tunnel-file write. When calling `restore-tunnel-config.ps1` directly, use `-CloudflaredExe <path>` if it is not on PATH; without a CLI, the helper warns that only structural/semantic checks ran. Validation refusal leaves both the existing tunnel config and credentials untouched.

The script discovers the extracted root and current user profile, restores the token and tunnel files, creates the virtual environment, reuses the project's hardened autostart chain (`install-autostart.ps1`, `install-tunnel-autostart.ps1`, `start.ps1`), and starts the server and Named Tunnel. It asks for an exact `YES` confirmation after warning that the old PC must be stopped first.

## Verify and clean up

```powershell
Invoke-WebRequest http://127.0.0.1:<port>/healthz
.\scripts\status.ps1
```

The local port comes from the migrated `config.json`. Confirm the public MCP URL and all seven tools from the new PC. Stop the old node before starting the same Named Tunnel, then delete the MOVE ZIP and any extracted credential copies once the migration is verified.
