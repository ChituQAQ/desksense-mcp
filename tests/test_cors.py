"""CORS behavior for local browser and configured remote origins."""
from __future__ import annotations

import pytest

httpx2 = pytest.importorskip("httpx2")

from desksense.config import Config
from desksense.server import ALLOW_HEADERS, EXPOSE_HEADERS, build_app


@pytest.fixture
def app_factory(tmp_path, monkeypatch):
    import desksense.config as config_module
    import desksense.server as server_module

    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(server_module, "_configure_logging", lambda cfg: None)
    monkeypatch.setattr(server_module.FocusHistory, "start_monitor", lambda self, _: None)

    histories = []

    def make(origins):
        app, history, _ = build_app(Config({"allowed_origins": origins}))
        histories.append(history)
        return app

    yield make
    for history in histories:
        history.stop_monitor()


async def _preflight(app, origin):
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.options(
            "/mcp",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "authorization,content-type,mcp-protocol-version,"
                    "mcp-session-id,accept"
                ),
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:43127",
        "http://127.0.0.1:43128",
        "http://[::1]:43129",
    ],
)
async def test_local_browser_origins_allow_any_port(app_factory, origin):
    response = await _preflight(app_factory([]), origin)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    allowed = response.headers["access-control-allow-headers"].lower()
    for header in ALLOW_HEADERS:
        assert header.lower() in allowed


@pytest.mark.asyncio
async def test_configured_https_origin_is_exactly_allowed(app_factory):
    origin = "https://client.example.com"
    response = await _preflight(app_factory([origin]), origin)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin

    denied = await _preflight(app_factory([origin]), "https://other.example.com")
    assert denied.headers.get("access-control-allow-origin") is None


@pytest.mark.asyncio
async def test_unauthorized_mcp_keeps_cors_headers_for_allowed_origins(app_factory):
    # 契约（scripts/verify-install.py）：未授权 401 也必须带 CORS 头，
    # 否则浏览器端 JS 读不到 401 状态，无法得知"是没带 token"。
    # 回归背景：中间件顺序曾把 Bearer 放到 CORS 外层，401 短路丢头（冷环境 CI 抓到）。
    for origin in ("https://client.example.com", "http://localhost:43110"):
        transport = httpx2.ASGITransport(app=app_factory(["https://client.example.com"]))
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/mcp",
                headers={"Origin": origin, "Content-Type": "application/json"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
        assert response.status_code == 401
        assert response.headers["access-control-allow-origin"] == origin
        exposed = response.headers.get("access-control-expose-headers", "").lower()
        assert "mcp-session-id" in exposed


def test_mcp_session_id_is_exposed():
    assert [header.lower() for header in EXPOSE_HEADERS] == ["mcp-session-id"]
