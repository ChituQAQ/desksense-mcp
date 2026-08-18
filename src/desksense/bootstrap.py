"""First-install token and config bootstrap helpers."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Sequence

from .auth import generate_api_key

TOKEN_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def ensure_api_key(path: Path) -> bool:
    """Create a 64-hex token if missing; return True only when created."""
    path = Path(path)
    if path.exists():
        token = path.read_text(encoding="utf-8-sig").strip()
        if not TOKEN_PATTERN.fullmatch(token):
            raise ValueError(f"Existing token has an unexpected format: {path}")
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    token = generate_api_key()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(token + "\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return True


def update_config(path: Path, port: int, allowed_origins: Sequence[str]) -> None:
    """Update installer-owned settings while preserving all other settings."""
    if not 1 <= int(port) <= 65535:
        raise ValueError("Port must be between 1 and 65535.")

    path = Path(path)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Existing config is not valid UTF-8 JSON: {path}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Existing config must contain a JSON object: {path}")

    data["host"] = "127.0.0.1"
    data["port"] = int(port)
    data["allowed_origins"] = list(dict.fromkeys(allowed_origins))
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--allowed-origin", action="append", default=[])
    args = parser.parse_args()

    root = args.root.resolve()
    created = ensure_api_key(root / ".secrets" / "API_KEY.txt")
    update_config(root / "config.json", args.port, args.allowed_origin)
    print("created" if created else "retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
