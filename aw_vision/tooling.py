"""Unified ReAct tool layer.

One canonical place for everything tool-related, shared by EVERY ReAct agent
in the system — the Ask Memory Agent and the pipeline classification prompts
alike:

- ``ToolSpec``: a uniform callable tool descriptor (builtin python functions
  and MCP tools look identical to the model).
- ``parse_tool_call`` / ``TOOL_CALL_RE``: the single CALL_TOOL protocol parser.
- ``format_tools_block``: renders the tool list + protocol instructions that
  get appended to any prompt that has tools available.
- ``run_react_loop``: a bounded observe→act loop for one-shot pipeline prompts,
  emitting structured tool events for logs/UI.

Separation of concerns: TOOLS are callable (builtin/MCP, dispatched here),
SKILLS are instructions (injected as guidance blocks by ``skills.py``); both
are assigned per prompt slot.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

TOOL_CALL_RE = re.compile(r"CALL_TOOL:\s*(\w+),\s*(.*)")

# Result text is bounded before being fed back into a model observation.
MAX_OBSERVATION_CHARS = 3000


@dataclass
class ToolSpec:
    name: str
    description: str
    run: Callable[[str], str]
    source: str = "builtin"  # "builtin" | "mcp"
    extra: Dict[str, Any] = field(default_factory=dict)


def extract_json_object(text: str) -> str:
    """Best-effort extraction of the outermost JSON object from a model reply.

    ReAct turns run without a JSON grammar constraint, so the final answer may
    be wrapped in prose or code fences. Returns "{}" when nothing parses.
    """
    text = (text or "").strip()
    try:
        json.loads(text)
        return text
    except Exception:
        pass
    start, stop = text.find("{"), text.rfind("}") + 1
    if 0 <= start < stop - 1:
        candidate = text[start:stop]
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass
    return "{}"


def parse_tool_call(text: str) -> Optional[Tuple[str, str]]:
    """Extract (tool_name, arg_string) from a model reply using the canonical protocol."""
    match = TOOL_CALL_RE.search(text or "")
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def format_tools_block(tools: List[ToolSpec]) -> str:
    """Uniform tool list + CALL_TOOL protocol instructions for any ReAct prompt."""
    if not tools:
        return ""
    lines = [
        "AVAILABLE TOOLS (call them when external evidence would materially improve your answer):",
    ]
    for t in tools:
        desc = (t.description or "External tool.").strip()
        if len(desc) > 160:
            desc = desc[:160] + "..."
        lines.append(f"- {t.name}(input): [{t.source}] {desc}")
    lines += [
        "",
        "TOOL PROTOCOL:",
        "1. To call a tool, output a single line exactly matching: CALL_TOOL: tool_name, argument_string",
        "   The argument may be a plain string OR a compact JSON object of named arguments.",
        "2. One tool call per turn; you will receive the result as a TOOL RESULT observation and may then call another tool or answer.",
        "3. When you have enough evidence, output ONLY your final answer with no CALL_TOOL line.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP tools as uniform ToolSpecs
# ---------------------------------------------------------------------------


def _slugify(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", value or "").strip("_").lower()
    return slug or fallback


def _mcp_runner(server_id: str, tool_name: str, schema: Dict[str, Any]) -> Callable[[str], str]:
    def run(raw_arg: str) -> str:
        from aw_vision.mcp_manager import mcp_manager

        arguments: Dict[str, Any] = {}
        raw = (raw_arg or "").strip()
        if raw and raw.lower() != "none":
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    arguments = parsed
                else:
                    arguments = mcp_manager._build_query_args({"input_schema": schema}, str(parsed))
            except (json.JSONDecodeError, ValueError):
                arguments = mcp_manager._build_query_args({"input_schema": schema}, raw)
        return mcp_manager.call_tool(server_id, tool_name, arguments)

    return run


def mcp_tools_for_slot(slot: str) -> List[ToolSpec]:
    """All MCP tools assigned to ``slot``, wrapped as uniform ToolSpecs.

    Names follow ``mcp_<tool>`` (disambiguated with the server slug on
    collision). Discovery failures degrade to an empty list so no agent ever
    breaks because an MCP server is down.
    """
    try:
        from aw_vision.mcp_manager import mcp_manager

        pairs = mcp_manager.tools_for_slot(slot)
    except Exception as e:
        print(f"[Tooling] Failed to load MCP tools for slot '{slot}': {e}")
        return []

    specs: List[ToolSpec] = []
    seen = set()
    for cfg, tool in pairs:
        base = _slugify(tool.get("name", "tool"), "tool")
        name = f"mcp_{base}"
        if name in seen:
            name = f"mcp_{_slugify(cfg.get('name', 'srv'), 'srv')}_{base}"
        seen.add(name)
        schema = tool.get("input_schema") or {}
        specs.append(
            ToolSpec(
                name=name,
                description=(tool.get("description") or "").strip(),
                run=_mcp_runner(cfg["id"], tool.get("name"), schema),
                source="mcp",
                extra={"server_name": cfg.get("name", "MCP Server"), "schema": schema},
            )
        )
    return specs


# ---------------------------------------------------------------------------
# Shared execution & the bounded ReAct loop
# ---------------------------------------------------------------------------


def execute_tool(tools: Dict[str, ToolSpec], name: str, arg: str) -> Dict[str, Any]:
    """Execute one tool uniformly, returning a structured event for logs/UI."""
    start = time.time()
    event: Dict[str, Any] = {"tool": name, "args": arg, "source": "builtin", "error": False}
    spec = tools.get(name)
    if not spec:
        event["error"] = True
        result = f"Tool '{name}' is not registered."
    else:
        event["source"] = spec.source
        try:
            result = spec.run(arg) or "[tool returned no textual content]"
        except Exception as e:
            event["error"] = True
            result = f"Error executing tool '{name}': {e}"
    event["duration_seconds"] = round(time.time() - start, 2)
    event["result"] = result
    event["result_preview"] = result[:800]
    return event


def run_react_loop(
    llm_fn: Callable[[List[Dict[str, str]], bool], str],
    base_prompt: str,
    tools: List[ToolSpec],
    max_steps: int = 2,
    log: Optional[Callable[[str], None]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Bounded ReAct loop for one-shot pipeline prompts.

    ``llm_fn(messages, force_json)`` runs one model turn over chat ``messages``
    ([{"role", "content"}]). While the model emits CALL_TOOL lines (up to
    ``max_steps`` of them) tools are executed and appended as observations;
    the final turn is forced to JSON. With no tools the model is called once,
    preserving the pre-ReAct single-shot behavior exactly.
    """
    tool_map = {t.name: t for t in tools}
    events: List[Dict[str, Any]] = []
    messages: List[Dict[str, str]] = [{"role": "user", "content": base_prompt}]

    if not tools:
        return llm_fn(messages, True), events

    steps = 0
    while True:
        force_json = steps >= max_steps
        reply = llm_fn(messages, force_json)
        call = None if force_json else parse_tool_call(reply)
        if not call:
            return reply, events

        name, arg = call
        if log:
            log(f"ReAct tool call {steps + 1}/{max_steps}: {name}({arg[:120]})")
        event = execute_tool(tool_map, name, arg)
        events.append(event)
        observation = event["result"]
        if len(observation) > MAX_OBSERVATION_CHARS:
            observation = observation[:MAX_OBSERVATION_CHARS] + "\n... [truncated]"
        messages.append({"role": "assistant", "content": reply})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"=== TOOL RESULT ({name}) ===\n{observation}\n\n"
                    "Use this evidence. Call another tool only if strictly necessary; otherwise output the final JSON answer now."
                ),
            }
        )
        steps += 1
