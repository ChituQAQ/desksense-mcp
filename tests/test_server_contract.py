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
