"""DeskSense — Streamable HTTP 服务入口。

使用官方 MCP Python SDK (mcp>=2.0) 的 MCPServer + streamable_http_app()。

端点设计：
  POST /mcp      : MCP Streamable HTTP 单端点（需静态 Bearer Token）
  GET  /healthz  : 健康检查（无需认证）
  OPTIONS        : CORS 预检（无需认证）

兼容 MCP protocol 2025-03-26 及更新版本（SDK 握手协商）。
"""

from __future__ import annotations

import contextlib
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

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
from mcp.server.transport_security import TransportSecuritySettings

SERVICE_NAME = "DeskSense MCP"
SERVICE_VERSION = "1.0.1"

logger = logging.getLogger("desksense")

ALLOW_HEADERS = [
    "Content-Type",
    "Authorization",
    "Mcp-Protocol-Version",
    "Mcp-Session-Id",
    "Accept",
]
EXPOSE_HEADERS = ["Mcp-Session-Id"]
LOCAL_CORS_ORIGIN_REGEX = (
    r"^https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?$"
)
LOCAL_TRANSPORT_ORIGINS = [
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
    "https://127.0.0.1:*",
    "https://localhost:*",
    "https://[::1]:*",
]


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
    root = logging.getLogger("desksense")
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

    @server.tool(name="pc_get_context", description="【综合工具】一次返回当前电脑整体状态：正在使用的前台应用、窗口标题、闲置状态、主要打开应用（最多约 15 个）、CPU、内存与开机时间。当用户谈论“我现在在电脑上做什么”“刚才在干什么”或询问电脑当前状态而未指定具体细节时，一条调用即可给出全局快照。适合在回答明显依赖用户当前电脑现场时作为默认入口。")
    def _impl_get_context() -> Dict[str, Any]:
        return pc_get_context(cfg, history)

    @server.tool(name="pc_get_focus", description="获取用户此刻正在使用的单一前台窗口：返回进程名、可执行文件路径、PID 与窗口标题。当用户问“我现在在看什么”“我正在用哪个软件”“当前窗口是什么”时，这是最精准的直接答案，比综合工具更聚焦、开销更低。")
    def _impl_get_focus() -> Dict[str, Any]:
        return pc_get_focus(cfg, include_path=True)

    @server.tool(name="pc_list_open_apps", description="列出用户当前打开着的所有桌面应用窗口（可见顶层窗口，按应用聚合，可选附带窗口标题），即用户肉眼看到的程序清单，而非后台进程。当话题涉及“我开了哪些窗口”“我正在用多少/哪些软件”或需要枚举当前工作环境时调用。")
    def _impl_list_open_apps(include_titles: bool = True, limit: int = 30) -> Dict[str, Any]:
        return pc_list_open_apps(cfg, include_titles=include_titles, limit=limit)

    @server.tool(name="pc_get_idle_status", description="返回用户距上次键盘/鼠标操作已过去多久：idle_seconds 与状态 active(<60s)/idle(60–300s)/away(>300s)。当话题涉及“我离开电脑多久”“现在是否仍在电脑前”“电脑多久没有操作”时调用，常用于判断用户当前是否在场。")
    def _impl_get_idle_status() -> Dict[str, Any]:
        return pc_get_idle_status(cfg)

    @server.tool(name="pc_get_pc_status", description="获取 PC 硬件/系统整体健康状态（只读）：CPU 使用率、内存容量与使用率、磁盘容量与使用率、开机时间、网络累计收发字节。当话题关于“电脑卡不卡/内存够不够/磁盘剩多少/开机多久/运行了多久”这类性能体检时调用。")
    def _impl_get_pc_status() -> Dict[str, Any]:
        return pc_get_pc_status(cfg)

    @server.tool(name="pc_get_top_processes", description="列出当前资源占用最高的进程（可按 CPU 或内存排序，默认内存，返回条数可调）。当话题关于“是什么在占用我的电脑/哪个程序最耗资源/电脑为什么慢”这类性能排查时调用，比综合工具给出的顶栏快照更详细。")
    def _impl_get_top_processes(sort_by: str = "memory", limit: int = 10) -> Dict[str, Any]:
        return pc_get_top_processes(cfg, sort_by=sort_by, limit=limit)

    @server.tool(name="pc_get_recent_focus", description="返回用户最近的前台程序切换时间线（后台每约 1 秒采样前台窗口，仅在进程或窗口标题变化时记录；可按分钟/条数截取，时间升序）。当话题关于“我刚才/最近在电脑上做了什么”“几分钟前在用什么软件”“这段时间的专注或切换轨迹”时，用于还原近期前台应用与窗口切换轨迹。")
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
    configured_origins = [str(origin) for origin in cfg.allowed_origins if origin]
    configured_hosts = []
    for origin in configured_origins:
        parsed = urlsplit(origin)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            configured_hosts.append(parsed.netloc)

    _ts = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"]
        + configured_hosts,
        allowed_origins=LOCAL_TRANSPORT_ORIGINS + configured_origins,
    )
    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        host=cfg.host,
        transport_security=_ts,
    )

    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.routing import Mount

    # SDK 返回的 Starlette app 自带 lifespan（管理 MCP 会话资源）；
    # 外层再包一层 Starlette：保留内层 lifespan，并在 ASGI 关闭后
    # 停止焦点监控线程、释放 SQLite 连接。
    inner_lifespan = mcp_app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def _lifespan(app):
        async with inner_lifespan(mcp_app):
            yield
        history.stop_monitor()
        history.close()

    app = Starlette(
        routes=[Mount("/", app=mcp_app)],
        middleware=[
            # 列表第一项在最外层：CORS 必须包住 Bearer 守卫，
            # 未授权 401 响应也要带上 allow-origin/expose-headers 头。
            Middleware(
                CORSMiddleware,
                allow_origins=configured_origins,
                allow_origin_regex=LOCAL_CORS_ORIGIN_REGEX,
                allow_methods=["*"],
                allow_headers=ALLOW_HEADERS,
                expose_headers=EXPOSE_HEADERS,
            ),
            Middleware(BearerAuthMiddleware, cfg),
        ],
        lifespan=_lifespan,
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
