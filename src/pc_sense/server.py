"""PC Sense MCP — Streamable HTTP 服务入口。

使用官方 MCP Python SDK (mcp>=2.0) 的 MCPServer + streamable_http_app()。

端点设计：
  POST /mcp      : MCP Streamable HTTP 单端点（需静态 Bearer Token）
  GET  /healthz  : 健康检查（无需认证）
  OPTIONS        : CORS 预检（无需认证）

兼容 MCP protocol 2025-03-26 及更新版本（SDK 握手协商）。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional

from starlette.responses import JSONResponse

from .auth import check_token, extract_bearer
from .config import Config, load_config
from .focus_history import FocusHistory
from .tools import (
    pc_get_context,
    pc_get_focus,
    pc_get_idle_status,
    pc_get_pc_status,
    pc_get_recent_focus,
    pc_get_top_processes,
    pc_list_open_apps,
)

from mcp.server.mcpserver import MCPServer

SERVICE_NAME = "PC Sense MCP"
SERVICE_VERSION = "1.0.0"

logger = logging.getLogger("pc_sense")

ALLOW_HEADERS = [
    "Content-Type",
    "Authorization",
    "Mcp-Protocol-Version",
    "Mcp-Session-Id",
    "Accept",
]
EXPOSE_HEADERS = ["Mcp-Session-Id"]


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
def _configure_logging(cfg: Config) -> None:
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        cfg.log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger("pc_sense")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.propagate = False


# ---------------------------------------------------------------------------
# 静态 Bearer Token ASGI 守卫（仅保护 /mcp，/healthz 与 OPTIONS 放行）
# ---------------------------------------------------------------------------
class BearerAuthMiddleware:
    def __init__(self, app, cfg: Config):
        self.app = app
        self.cfg = cfg

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method")
        path = scope.get("path", "")
        # OPTIONS 与 /mcp 之外的路径放行
        if method == "OPTIONS" or path.rstrip("/") != "/mcp":
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        token = extract_bearer(headers.get("authorization"))
        if not token or not check_token(token, self.cfg):
            resp = JSONResponse(
                {"error": "unauthorized", "detail": "invalid or missing bearer token"},
                status_code=401,
            )
            await resp(scope, receive, send)
            return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
def _create_server(cfg: Config, history: FocusHistory) -> MCPServer:
    server = MCPServer(
        name=SERVICE_NAME,
        version=SERVICE_VERSION,
        description="Windows 本机电脑感知 MCP（只读）。可查询当前前台程序、打开的窗口、闲置时间、系统负载与焦点切换历史。",
    )

    @server.tool(name="pc_get_context", description="【默认综合工具】一次返回当前电脑整体状态：前台应用、当前窗口标题、pid、闲置状态、主要打开应用（最多约 15 个）、CPU、内存、开机时间、固定磁盘概览。当用户说“看看我电脑 / 我电脑上在干嘛 / 我现在电脑什么状态”时优先调用本工具。")
    def _impl_get_context() -> Dict[str, Any]:
        return pc_get_context(cfg, history)

    @server.tool(name="pc_get_focus", description="获取当前前台窗口信息：使用 Windows API (GetForegroundWindow/GetWindowText/GetWindowThreadProcessId) 结合 psutil，返回 pid、进程名、可执行文件路径（安全时）、窗口标题。")
    def _impl_get_focus() -> Dict[str, Any]:
        return pc_get_focus(cfg, include_path=True)

    @server.tool(name="pc_list_open_apps", description="列出用户当前“打开着的”桌面应用窗口（可见顶层窗口，过滤不可见/空标题/tool window/cloaked 系统噪音，按应用聚合）。返回的是用户肉眼看到的打开程序，不是后台服务进程。include_titles 控制是否附带窗口标题，limit 控制返回应用数上限。")
    def _impl_list_open_apps(include_titles: bool = True, limit: int = 30) -> Dict[str, Any]:
        return pc_list_open_apps(cfg, include_titles=include_titles, limit=limit)

    @server.tool(name="pc_get_idle_status", description="获取用户多久没有操作电脑（键盘/鼠标）。返回 idle_seconds 与 state：active(<60s)/idle(60–300s)/away(>300s)。")
    def _impl_get_idle_status() -> Dict[str, Any]:
        return pc_get_idle_status(cfg)

    @server.tool(name="pc_get_pc_status", description="获取 PC 整体状态（只读）：CPU 使用率、物理内存总量与使用率、固定磁盘容量与使用率、开机时间、网络累计收发字节。")
    def _impl_get_pc_status() -> Dict[str, Any]:
        return pc_get_pc_status(cfg)

    @server.tool(name="pc_get_top_processes", description="列出资源占用最高的进程。limit 控制返回条数（默认 10，上限 30）；sort_by 可选 'cpu' 或 'memory'（默认 memory）。CPU 统计有短暂采样以确保非零。")
    def _impl_get_top_processes(sort_by: str = "memory", limit: int = 10) -> Dict[str, Any]:
        return pc_get_top_processes(cfg, sort_by=sort_by, limit=limit)

    @server.tool(name="pc_get_recent_focus", description="查询最近前台程序切换历史。后台每约 1 秒检测前台窗口，仅在进程或窗口标题变化时写入 SQLite。minutes 查询最近几分钟（默认 30，上限 1440），limit 限制返回条数（默认 100，上限 500）。按时间升序返回。")
    def _impl_get_recent_focus(minutes: int = 30, limit: int = 100) -> Dict[str, Any]:
        return pc_get_recent_focus(cfg, history, minutes=minutes, limit=limit)

    @server.custom_route("/healthz", methods=["GET"])
    async def _healthz(request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": SERVICE_NAME})

    return server


# ---------------------------------------------------------------------------
# 顶层构建
# ---------------------------------------------------------------------------
def build_app(cfg: Optional[Config] = None):
    """构造完整 app，返回 (app, history, cfg)。"""
    cfg = cfg or load_config()
    _configure_logging(cfg)

    history = FocusHistory(cfg.db_path, retention_days=cfg.history_retention_days)
    history.start_monitor(cfg.focus_poll_interval)
    logger.info("focus history monitor 已启动 @ %s", cfg.db_path)

    server = _create_server(cfg, history)
    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        host=cfg.host,
    )

    from starlette.middleware.cors import CORSMiddleware

    app = CORSMiddleware(
        BearerAuthMiddleware(mcp_app, cfg),
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=ALLOW_HEADERS,
        expose_headers=EXPOSE_HEADERS,
    )
    return app, history, cfg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    import uvicorn

    cfg = load_config()
    app, _hist, _cfg = build_app(cfg)
    logger.info("%s 启动 @ http://%s:%d/mcp", SERVICE_NAME, cfg.host, cfg.port)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()