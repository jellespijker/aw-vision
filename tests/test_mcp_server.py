"""Smoke tests for the outward-facing aw-vision MCP server."""

import asyncio
import os

os.environ.setdefault("LANCE_DB_DIR", "/tmp/test_aw_vision_db")

from aw_vision import mcp_server  # noqa: E402

EXPECTED_READ_TOOLS = {
    "search_screenshots_semantic",
    "find_person_moments",
    "get_activity_for_timeframe",
    "get_recent_screenshots",
    "get_active_projects",
    "aggregate_project_hours",
}


def test_exposes_exactly_the_read_tier_tools():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == EXPECTED_READ_TOOLS
    # Every exposed tool must be self-describing for external clients.
    assert all(t.description for t in tools)
    # Write/act capabilities must never leak outward.
    assert "execute_command" not in names
    assert not any("relabel" in n or "delete" in n for n in names)


def test_tool_invocation_round_trip():
    # FastMCP returns (content_blocks, structured_result).
    blocks, structured = asyncio.run(mcp_server.mcp.call_tool("get_active_projects", {}))
    text = "".join(getattr(block, "text", "") for block in blocks)
    assert isinstance(text, str) and len(text) > 0
    assert structured.get("result") == text
