"""Tests for native tool-call schemas and normalization (ADR-0006)."""

import os

os.environ.setdefault("LANCE_DB_DIR", "/tmp/test_aw_vision_db")

from aw_vision.tooling import ToolSpec, normalize_native_call, parse_tool_call, to_ollama_tools  # noqa: E402


def _spec(name, schema=None):
    return ToolSpec(name=name, description="d", run=lambda a: a, extra={"schema": schema} if schema else {})


def test_to_ollama_tools_uses_mcp_schema_and_string_default():
    mcp_schema = {"type": "object", "properties": {"jql": {"type": "string"}}, "required": ["jql"]}
    out = to_ollama_tools([_spec("builtin_one"), _spec("mcp_search", mcp_schema)])
    assert out[0]["function"]["parameters"]["properties"] == {
        "input": {"type": "string", "description": "The tool's single input argument."}
    }
    assert out[1]["function"]["parameters"] == mcp_schema
    assert all(t["type"] == "function" for t in out)


def test_normalize_native_call_collapses_single_input_and_keeps_json():
    assert normalize_native_call({"function": {"name": "t", "arguments": {"input": "15"}}}) == ("t", "15")
    name, arg = normalize_native_call({"function": {"name": "t", "arguments": {"jql": "project = A", "max": 5}}})
    assert name == "t"
    assert '"jql": "project = A"' in arg
    # String-encoded arguments and empty args degrade sanely
    assert normalize_native_call({"function": {"name": "t", "arguments": "plain query"}}) == ("t", "plain query")
    assert normalize_native_call({"function": {"name": "t"}}) == ("t", "")
    assert normalize_native_call({"function": {}}) is None


def test_normalized_line_round_trips_through_protocol_parser():
    name, arg = normalize_native_call({"function": {"name": "search", "arguments": {"input": "purple sneakers"}}})
    reply = f"Some reasoning.\n\nCALL_TOOL: {name}, {arg}"
    assert parse_tool_call(reply) == ("search", "purple sneakers")
