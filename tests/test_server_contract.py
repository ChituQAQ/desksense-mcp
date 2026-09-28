"""Server registration contract tests."""
from __future__ import annotations

import pytest

from desksense.config import Config
from desksense.focus_history import FocusHistory
from desksense.server import _create_server


EXPECTED_TOOLS = {
    "pc_get_context",
    "pc_get_focus",
    "pc_list_open_apps",
    "pc_get_idle_status",
    "pc_get_pc_status",
    "pc_get_top_processes",
    "pc_get_recent_focus",
}


@pytest.mark.asyncio
async def test_exactly_seven_tools_are_registered(tmp_path):
    history = FocusHistory(tmp_path / "history.db")
    try:
        server = _create_server(Config({}), history)
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == EXPECTED_TOOLS
    finally:
        history.stop_monitor()


@pytest.mark.asyncio
async def test_asgi_shutdown_stops_monitor_and_closes_db(tmp_path, monkeypatch):
    import desksense.config as config_module
    import desksense.server as server_module
    from starlette.testclient import TestClient

    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(server_module, "_configure_logging", lambda cfg: None)
    monkeypatch.setattr(
        "desksense.windows_focus.get_foreground_info",
        lambda: {"pid": None, "process_name": None, "window_title": None},
    )

    app, history, _cfg = server_module.build_app(Config({}))
    try:
        with TestClient(app, base_url="http://testserver") as client:
            assert client.get("/healthz").status_code == 200
            assert history._thread is not None and history._thread.is_alive()
        # ASGI 关闭后：监控线程必须停止，数据库连接必须释放（审计缺陷）。
        assert not history._thread.is_alive()
        assert history._db is None
    finally:
        history.close()
