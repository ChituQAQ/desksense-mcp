"""Verify one installed DeskSense endpoint without printing its bearer token."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = {
    "pc_get_context",
    "pc_get_focus",
    "pc_list_open_apps",
    "pc_get_idle_status",
    "pc_get_pc_status",
    "pc_get_top_processes",
    "pc_get_recent_focus",
}


async def verify_endpoint(base: str, token: str, origin: str, local: bool) -> None:
    timeout = httpx2.Timeout(20.0)
    async with httpx2.AsyncClient(timeout=timeout, trust_env=not local) as client:
        health = await client.get(base + "/healthz")
        assert health.status_code == 200, f"healthz returned {health.status_code}"

        unauthorized = await client.post(
            base + "/mcp",
            headers={"Origin": origin, "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert unauthorized.status_code == 401, (
            f"unauthenticated /mcp returned {unauthorized.status_code}"
        )
        assert unauthorized.headers.get("access-control-allow-origin") == origin
        exposed = unauthorized.headers.get("access-control-expose-headers", "").lower()
        assert "mcp-session-id" in exposed

        preflight = await client.options(
            base + "/mcp",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "authorization,content-type,mcp-protocol-version,"
                    "mcp-session-id,accept"
                ),
            },
        )
        assert preflight.status_code == 200, (
            f"CORS preflight returned {preflight.status_code}"
        )
        assert preflight.headers.get("access-control-allow-origin") == origin

    headers = {
        "Authorization": "Bearer " + token,
        "Origin": origin,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx2.AsyncClient(
        headers=headers, timeout=timeout, trust_env=not local
    ) as client:
        async with streamable_http_client(
            base + "/mcp", http_client=client
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert names == EXPECTED_TOOLS, f"unexpected tools: {sorted(names)}"
                context = await session.call_tool("pc_get_context", {})
                assert context.content and not context.is_error, "pc_get_context failed"


async def verify_with_retries(
    base: str, token: str, origin: str, local: bool, attempts: int, delay: float
) -> None:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            await verify_endpoint(base, token, origin, local)
            return
        except Exception as exc:  # noqa: BLE001 - preserve the final verification cause
            last_error = exc
            await asyncio.sleep(delay)
    assert last_error is not None
    raise last_error


async def run(args: argparse.Namespace) -> None:
    token = args.token_file.read_text(encoding="utf-8-sig").strip()
    if len(token) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in token):
        raise ValueError("Token file must contain exactly 64 hexadecimal characters.")

    await verify_with_retries(
        args.local_base, token, args.origin, True, args.local_attempts, 1.0
    )
    if args.public_base:
        await verify_with_retries(
            args.public_base, token, args.origin, False, args.public_attempts, 3.0
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-base", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--public-base")
    parser.add_argument("--local-attempts", type=int, default=30)
    parser.add_argument("--public-attempts", type=int, default=30)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args))
    if not args.quiet:
        print("health=ok tools=7 tool=pc_get_context")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
