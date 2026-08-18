"""端到端 Streamable HTTP MCP 集成测试。

直接连运行中的服务，覆盖：
  - initialize / 协议版本
  - tools/list（应含 7 个工具）
  - 逐个调用 7 个工具
  - 未授权访问应 401（单独的 HTTP 断言）

运行前需启动服务：
  cd desksense-mcp && .\\scripts\\start.ps1
用法:
  PYTHONPATH=src .venv\\Scripts\\python.exe scripts\\run_integration_test.py
"""
import asyncio
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import httpx2  # noqa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

API_KEY_PATH = ROOT / ".secrets" / "API_KEY.txt"
URL = "http://127.0.0.1:8765/mcp"

EXPECTED_TOOLS = {
    "pc_get_context",
    "pc_get_focus",
    "pc_list_open_apps",
    "pc_get_idle_status",
    "pc_get_pc_status",
    "pc_get_top_processes",
    "pc_get_recent_focus",
}


async def main() -> int:
    api_key = API_KEY_PATH.read_text(encoding="utf-8").strip()
    assert len(api_key) == 64, "API key 应为 64 位 hex"

    # ---- 未授权检查（直接 HTTP）----
    async with httpx2.AsyncClient() as c:
        r = await c.post(
            URL,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 401, f"无 token 应 401, got {r.status_code}"
        print("[OK] 无 token -> 401")

        r2 = await c.post(
            URL,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
        )
        assert r2.status_code == 401, f"错误 token 应 401, got {r2.status_code}"
        print("[OK] 错误 token -> 401")

    # ---- 带 token 的完整 MCP 会话 ----
    transport_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx2.AsyncClient(headers=transport_headers) as client:
        async with streamable_http_client(URL, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                print(f"[OK] initialize -> protocol_version={init.protocol_version} "
                      f"server={init.server_info.name} v{init.server_info.version}")
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                print(f"[OK] tools/list -> {len(names)} 个工具: {sorted(names)}")
                missing = EXPECTED_TOOLS - names
                assert not missing, f"缺少工具: {missing}"

                # 逐个调用（优先核心工具）
                calls = [
                    ("pc_get_context", {}),
                    ("pc_get_focus", {}),
                    ("pc_list_open_apps", {"limit": 10}),
                    ("pc_get_idle_status", {}),
                    ("pc_get_pc_status", {}),
                    ("pc_get_top_processes", {"sort_by": "memory", "limit": 5}),
                    ("pc_get_recent_focus", {"minutes": 30, "limit": 10}),
                ]
                for name, args in calls:
                    res = await session.call_tool(name, args)
                    # 汇总内容
                    texts = []
                    for block in res.content or []:
                        if getattr(block, "type", None) == "text":
                            texts.append(block.text)
                    joined = "\n".join(texts)
                    print(f"[OK] call_tool {name} -> {len(joined)} chars")
                    # 简单健壮性：必须是可解析 JSON 或合法文本
                    assert joined.strip(), f"{name} 返回空"

    print("\n全部集成测试通过 ✅")
    return 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except AssertionError as e:
        print(f"❌ 断言失败: {e}")
        code = 1
    except Exception as e:
        print(f"❌ 异常: {type(e).__name__}: {e}")
        code = 1
    sys.exit(code)