"""Safe, offline YAML handling for the MOVE PowerShell entry points.

Only selected ingress routes and origin defaults leave the source machine. Merges
insert a new block without reserializing existing text. Unsupported/ambiguous YAML
is refused rather than guessed. No credential contents are printed.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import yaml


class MoveError(ValueError):
    pass


class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        seen = set()
        for key, _ in node.value:
            if key.tag != "tag:yaml.org,2002:str" or key.value in seen:
                raise MoveError("Duplicate, merged, or non-string YAML keys are not supported.")
            seen.add(key.value)
        return super().construct_mapping(node, deep=deep)


class IndentedDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def parse_yaml(text):
    try:
        for event in yaml.parse(text):
            if getattr(event, "anchor", None) is not None:
                raise MoveError("YAML anchors/aliases are not supported for MOVE; expand them first.")
        loader = StrictLoader(text)
        try:
            node = loader.get_single_node()
            data = loader.construct_document(node) if node else None
        finally:
            loader.dispose()
        if not isinstance(data, dict):
            raise MoveError("Tunnel configuration must be a YAML mapping.")
        # Reject timestamps, binary objects, non-finite numbers, etc. rather than
        # changing their types while passing through the JSON manifest.
        json.dumps(data, allow_nan=False)
        return data, node
    except (yaml.YAMLError, TypeError, ValueError) as exc:
        if isinstance(exc, MoveError):
            raise
        # YAML exception messages can contain entire source lines (private data).
        raise MoveError("Invalid or unsupported YAML; no target files were changed.") from None


def dump_yaml(data):
    return yaml.dump(data, Dumper=IndentedDumper, sort_keys=False, allow_unicode=True)


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        raise MoveError("Required JSON file is missing or invalid.") from None
    if not isinstance(data, dict):
        raise MoveError("Expected a JSON object.")
    return data


def origin_defaults(config):
    defaults = config.get("originRequest", {})
    if not isinstance(defaults, dict):
        raise MoveError("originRequest must be a mapping.")
    return defaults


def is_catch_all(route):
    return route.get("hostname") in (None, "", "*") and not route.get("path")


def validate_routes(config):
    routes = config.get("ingress")
    if not isinstance(routes, list) or not routes:
        raise MoveError("Configuration needs ingress rules and a final catch-all.")
    origin_defaults(config)
    for route in routes:
        if not isinstance(route, dict) or not isinstance(route.get("service"), str) or not route["service"]:
            raise MoveError("Each ingress rule needs a non-empty service string.")
        for field in ("hostname", "path"):
            if field in route and not isinstance(route[field], str):
                raise MoveError("Ingress hostname/path must be strings.")
        origin_defaults(route)
    if not is_catch_all(routes[-1]) or any(is_catch_all(r) for r in routes[:-1]):
        raise MoveError("Ingress must end with exactly one catch-all (any service type).")
    return routes


def local_routes(config, port):
    from urllib.parse import urlsplit

    selected = []
    for route in validate_routes(config):
        try:
            url = urlsplit(route["service"])
            matches = (url.scheme in ("http", "https") and
                       url.hostname in ("localhost", "127.0.0.1", "::1") and url.port == port)
        except ValueError:
            matches = False
        if matches:
            if not route.get("hostname") or is_catch_all(route):
                raise MoveError("MOVE requires an explicit hostname for each exported Node route.")
            selected.append(copy.deepcopy(route))
    return selected


def credential_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.json", name):
        raise MoveError("Credential filename must be a plain JSON filename, not a path.")
    return name


def check_credential(path, tunnel_id):
    if read_json(path).get("TunnelID") != tunnel_id:
        raise MoveError("Credential TunnelID does not match the configured tunnel_id.")


def ensure_portable(routes, defaults):
    # caPool names a file on the old machine, not a value portable in the manifest.
    if defaults.get("caPool") or any(origin_defaults(r).get("caPool") for r in routes):
        raise MoveError("originRequest.caPool references a local file; migrate it explicitly before MOVE.")


def export_tunnel(root, cfd_home, stage, config_path=None):
    port = read_json(root / "config.json").get("port", 8765) if (root / "config.json").exists() else 8765
    if type(port) is not int or not 1 <= port <= 65535:
        raise MoveError("Invalid Node port.")
    paths = [config_path] if config_path else sorted(set(cfd_home.glob("*.yml")) | set(cfd_home.glob("*.yaml")))
    matches = []
    for path in paths:
        path = path.resolve()
        config, _ = parse_yaml(path.read_text(encoding="utf-8-sig"))
        routes = local_routes(config, port)
        if routes:
            matches.append((path, config, routes))
    if not matches:
        raise MoveError("no ingress route points at the Node port; select the correct -ConfigPath.")
    if len(matches) != 1:
        raise MoveError("Multiple tunnel configs match the Node port; specify -ConfigPath.")
    path, config, routes = matches[0]
    tunnel_id = config.get("tunnel")
    if not isinstance(tunnel_id, str) or not tunnel_id:
        raise MoveError("Tunnel configuration needs a tunnel ID.")
    source = config.get("credentials-file")
    if source is None:
        source = str(path.parent / credential_name(tunnel_id + ".json"))
    if not isinstance(source, str) or not Path(source).is_absolute():
        raise MoveError("credentials-file must be an absolute path; relative connector working directories are ambiguous.")
    credential = Path(source)
    name = credential_name(credential.name)
    check_credential(credential, tunnel_id)
    defaults = origin_defaults(config)
    ensure_portable(routes, defaults)
    manifest = {"tunnel_id": tunnel_id, "credentials_file": name,
                "hostname": routes[0]["hostname"], "routes": routes,
                "origin_request_defaults": defaults}
    destination = stage / "cloudflared"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(credential, destination / name)
    (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def hosts_overlap(left, right):
    left, right = left.lower(), right.lower()
    if left in ("", "*") or right in ("", "*") or left == right:
        return True
    return (left.startswith("*.") and right.endswith(left[1:])) or (
        right.startswith("*.") and left.endswith(right[1:])
    )


def merge_config(text, config, node, routes, defaults):
    existing = validate_routes(config)
    if origin_defaults(config) != defaults:
        raise MoveError("Source and target originRequest defaults differ; refusing to change routing semantics.")
    missing = []
    for route in routes:
        same_host = [r for r in existing[:-1] if r.get("hostname", "").lower() == route["hostname"].lower()]
        if same_host:
            if route not in same_host:
                raise MoveError("An archive hostname already has different routing/options; refusing to merge.")
        else:
            if any(hosts_overlap(r.get("hostname", ""), route["hostname"]) for r in existing[:-1]):
                raise MoveError("An existing wildcard/path rule may shadow the archive hostname; refusing to merge.")
            missing.append(route)
    if not missing:
        print("All archive routes already present; nothing to merge.")
        return text
    ingress_node = next(value for key, value in node.value if key.value == "ingress")
    if ingress_node.flow_style:
        raise MoveError("Cannot insert into a flow-style ingress without rewriting existing lines.")
    catch_node = ingress_node.value[-1]
    start = text.rfind("\n", 0, catch_node.start_mark.index) + 1
    prefix = text[start:catch_node.start_mark.index]
    match = re.fullmatch(r"( *)- +", prefix)
    if not match:
        raise MoveError("Unsupported catch-all layout; expand it to a block list before merging.")
    indent = match[1]
    newline = "\r\n" if "\r\n" in text else "\n"
    block = "".join(indent + line + newline for line in dump_yaml(missing).splitlines())
    candidate = text[:start] + block + text[start:]
    parsed, _ = parse_yaml(candidate)
    expected = copy.deepcopy(config)
    expected["ingress"] = existing[:-1] + missing + existing[-1:]
    if parsed != expected:
        raise MoveError("Candidate merge changes existing configuration; refusing to write.")
    validate_routes(parsed)
    return candidate


def validate_cloudflared(candidate, executable):
    if not executable:
        return  # Structural/semantic checks always run; installer supplies the CLI.
    with tempfile.TemporaryDirectory(prefix="desksense-ingress-") as tmp:
        path = Path(tmp) / "candidate.yml"
        path.write_bytes(candidate.encode("utf-8"))
        result = subprocess.run([executable, "tunnel", "--config", str(path), "ingress", "validate"],
                                capture_output=True, timeout=30)
        if result.returncode:
            raise MoveError("cloudflared rejected candidate ingress; target files are unchanged.")


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".desksense-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def restore_tunnel(manifest_file, archive, home, merge=False, cloudflared=None):
    home = home.resolve()
    manifest = read_json(manifest_file)
    tunnel_id = manifest.get("tunnel_id")
    if not isinstance(tunnel_id, str) or not tunnel_id:
        raise MoveError("manifest.json has no tunnel_id; re-export the archive.")
    name = credential_name(manifest.get("credentials_file", tunnel_id + ".json"))
    source = archive / name
    check_credential(source, tunnel_id)
    routes = manifest.get("routes")
    defaults = origin_defaults({"originRequest": manifest.get("origin_request_defaults", {})})
    if not routes:
        legacy_path = archive / "config.yml"
        if not legacy_path.exists():
            raise MoveError("Archive has no routes or config.yml; re-export the archive.")
        legacy, _ = parse_yaml(legacy_path.read_text(encoding="utf-8-sig"))
        routes = [r for r in validate_routes(legacy) if r.get("hostname") and not is_catch_all(r)][:1]
        defaults = origin_defaults(legacy)
        print("WARNING: Falling back to the first route in the legacy config.yml.")
    if not isinstance(routes, list) or not routes or any(not isinstance(r, dict) or not r.get("hostname") for r in routes):
        raise MoveError("Archive routes need explicit hostnames.")
    proposed = {"tunnel": tunnel_id, "credentials-file": str(home / name), "protocol": "http2",
                "ingress": routes + [{"service": "http_status:404"}]}
    if defaults:
        proposed["originRequest"] = defaults
    validate_routes(proposed)
    ensure_portable(routes, origin_defaults(proposed))
    path = home / "config.yml"
    before = path.read_bytes() if path.exists() else None
    if before is not None:
        text = before.decode("utf-8")  # Keep BOM and original newlines byte-for-byte.
        config, node = parse_yaml(text)
        if config.get("tunnel") != tunnel_id:
            raise MoveError("One config.yml serves exactly one tunnel; target tunnel differs.")
        if not merge:
            raise MoveError("Target config.yml already exists; use -MergeIngress explicitly.")
        candidate = merge_config(text, config, node, routes, defaults)
    else:
        candidate = dump_yaml(proposed)
        parsed, _ = parse_yaml(candidate)
        if parsed != proposed:
            raise MoveError("Manifest cannot be represented losslessly as YAML.")
    validate_cloudflared(candidate, cloudflared)
    # All validation happens before credentials or config are written.
    home.mkdir(parents=True, exist_ok=True)
    atomic_write(home / name, source.read_bytes())
    if candidate.encode("utf-8") != before:
        atomic_write(path, candidate.encode("utf-8"))
    print("Tunnel credential and configuration restored.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    export = actions.add_parser("export")
    for name in ("root", "cfd-home", "stage"):
        export.add_argument("--" + name, type=Path, required=True)
    export.add_argument("--config", type=Path)
    restore = actions.add_parser("restore")
    for name in ("manifest", "archive", "home"):
        restore.add_argument("--" + name, type=Path, required=True)
    restore.add_argument("--merge", action="store_true")
    restore.add_argument("--cloudflared")
    args = parser.parse_args()
    try:
        if args.action == "export":
            export_tunnel(args.root, args.cfd_home, args.stage, args.config)
        else:
            restore_tunnel(args.manifest, args.archive, args.home, args.merge, args.cloudflared)
    except MoveError as exc:
        print("ERROR: " + str(exc))
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        print("ERROR: MOVE failed to read, validate or write its files; check paths and permissions.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
