"""MCP (Model Context Protocol) integration layer.

This module provides:
- Persistent, hardware-encrypted storage of MCP server configurations (local stdio
  servers as well as remote HTTP/SSE servers with token authentication).
- A synchronous facade over the asynchronous ``mcp`` client SDK so the rest of the
  (thread-based) backend can connect, introspect tools, and invoke tools without
  having to care about asyncio event loops.
- A slot-based assignment model that lets each MCP server be wired into individual
  prompts of the ingestion pipeline and/or the Ask Memory Agent.

NOTE: this file is intentionally NOT named ``mcp.py`` so it does not shadow the
official ``mcp`` SDK package on the import path.
"""

import concurrent.futures
import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from aw_vision.config import config
from aw_vision.kvstore import LanceKVStore
from aw_vision.mcp_session import SessionPool
from aw_vision.settings import decrypt_value, encrypt_value

# ---------------------------------------------------------------------------
# Assignable pipeline / agent slots
# ---------------------------------------------------------------------------
# Each "slot" represents an individual prompt (or the agent) that an MCP server
# can be attached to, giving the user fine-grained control over where in the
# pipeline external tools are allowed to be consulted.
SLOTS: List[Dict[str, str]] = [
    {"id": "agent", "label": "Ask Memory Agent", "group": "Agent"},
    {"id": "local_vision", "label": "Local Vision Pass (window · desktop · artifacts)", "group": "Local Pipeline"},
    {"id": "local_synthesis", "label": "Local Synthesis (classification · tags · description)", "group": "Local Pipeline"},
    {"id": "gemini_combined", "label": "Gemini Combined OCR + Vision", "group": "Cloud Pipeline"},
]

VALID_SLOT_IDS = {s["id"] for s in SLOTS}

SECRET_MASK = "••••••••"

# Keywords used to heuristically pick a "lookup" style tool when auto-enriching a
# pipeline prompt with external MCP context.
_LOOKUP_KEYWORDS = ("search", "find", "query", "list", "get", "lookup", "issues", "pulls", "repos")
# Property names that tend to carry a free-text query argument.
_QUERY_PROP_NAMES = ("query", "q", "jql", "keywords", "search", "text", "term", "prompt")


def _coerce_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip():
        # Allow whitespace separated args entered as a single string.
        return value.split()
    return []


def normalize_server(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce an arbitrary incoming dict into a fully-formed server config."""
    transport = (raw.get("transport") or "stdio").lower()
    if transport not in ("stdio", "http", "sse"):
        transport = "stdio"

    auth_type = (raw.get("auth_type") or "none").lower()
    if auth_type not in ("none", "bearer", "header"):
        auth_type = "none"

    env_raw = raw.get("env") or {}
    if not isinstance(env_raw, dict):
        env_raw = {}

    assignments = [a for a in (raw.get("assignments") or []) if a in VALID_SLOT_IDS]

    return {
        "id": raw.get("id") or uuid.uuid4().hex[:12],
        "name": (raw.get("name") or "Unnamed MCP Server").strip(),
        "enabled": bool(raw.get("enabled", True)),
        "transport": transport,
        # stdio (local) transport
        "command": (raw.get("command") or "").strip(),
        "args": _coerce_str_list(raw.get("args")),
        "env": {str(k): str(v) for k, v in env_raw.items()},
        "cwd": (raw.get("cwd") or "").strip(),
        # http / sse (remote) transport
        "url": (raw.get("url") or "").strip(),
        "auth_type": auth_type,
        "auth_token": raw.get("auth_token") or "",
        "header_name": (raw.get("header_name") or "Authorization").strip() or "Authorization",
        # routing
        "assignments": assignments,
    }


class MCPStore:
    """Persist MCP server configurations in LanceDB, encrypting the whole blob at rest."""

    def __init__(self):
        self._kv = LanceKVStore("mcp_servers", key_field="id", value_field="blob")
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.load_all()

    def load_all(self):
        self._cache = {}
        for row_id, blob in self._kv.items(limit=1000).items():
            if not blob:
                continue
            try:
                decrypted = decrypt_value(blob)
                data = json.loads(decrypted) if decrypted else None
                if data and data.get("id"):
                    self._cache[data["id"]] = normalize_server(data)
            except Exception as e:
                print(f"Warning: could not decode MCP server row {row_id}: {e}")

    def list(self) -> List[Dict[str, Any]]:
        return [dict(v) for v in self._cache.values()]

    def get(self, server_id: str) -> Optional[Dict[str, Any]]:
        cfg = self._cache.get(server_id)
        return dict(cfg) if cfg else None

    def save(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        cfg = normalize_server(raw)
        # Preserve an existing secret if the frontend sent back the mask placeholder.
        existing = self._cache.get(cfg["id"])
        if existing and cfg.get("auth_token") in ("", SECRET_MASK):
            if cfg.get("auth_token") == SECRET_MASK:
                cfg["auth_token"] = existing.get("auth_token", "")
        self._cache[cfg["id"]] = cfg

        self._kv.upsert(cfg["id"], encrypt_value(json.dumps(cfg)))
        return cfg

    def delete(self, server_id: str) -> bool:
        existed = server_id in self._cache
        self._cache.pop(server_id, None)
        self._kv.delete(server_id)
        return existed


def mask_server(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy safe to send to the frontend (secrets masked)."""
    out = dict(cfg)
    out["auth_token"] = SECRET_MASK if cfg.get("auth_token") else ""
    if cfg.get("env"):
        out["env"] = {k: SECRET_MASK if v else "" for k, v in cfg["env"].items()}
    return out


class MCPManager:
    """Synchronous facade over the asynchronous MCP client SDK."""

    def __init__(self, store: MCPStore):
        self.store = store
        # Cache of discovered tools keyed by a hash of the connection config.
        self._tool_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._tool_cache_ttl = 300.0
        # Persistent per-server sessions with circuit breaking (mcp_session.py).
        self.pool = SessionPool(self._open_transport, self._cache_key)

    def health(self, server_id: str) -> Dict[str, Any]:
        return self.pool.breaker(server_id).health()

    # -- persistent session plumbing ----------------------------------------
    @staticmethod
    def _build_headers(cfg: Dict[str, Any]) -> Optional[Dict[str, str]]:
        auth_type = cfg.get("auth_type", "none")
        token = cfg.get("auth_token") or ""
        if auth_type == "none" or not token:
            return None
        if auth_type == "bearer":
            return {"Authorization": f"Bearer {token}"}
        if auth_type == "header":
            return {cfg.get("header_name") or "Authorization": token}
        return None

    @classmethod
    async def _open_transport(cls, stack, cfg: Dict[str, Any]):
        """Enter the transport + ClientSession context managers on ``stack`` and
        return the initialized session (kept alive by the owning SessionWorker)."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        transport = cfg.get("transport", "stdio")

        if transport == "stdio":
            command = cfg.get("command")
            if not command:
                raise ValueError("Local (stdio) MCP server requires a command.")
            env = None
            if cfg.get("env"):
                try:
                    from mcp.client.stdio import get_default_environment

                    env = {**get_default_environment(), **cfg["env"]}
                except Exception:
                    env = dict(cfg["env"])
            params = StdioServerParameters(
                command=command,
                args=cfg.get("args") or [],
                env=env,
                cwd=cfg.get("cwd") or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        elif transport == "http":
            from mcp.client.streamable_http import streamablehttp_client

            if not cfg.get("url"):
                raise ValueError("Remote MCP server requires a URL.")
            read, write, _get_sid = await stack.enter_async_context(
                streamablehttp_client(cfg["url"], headers=cls._build_headers(cfg))
            )
        elif transport == "sse":
            from mcp.client.sse import sse_client

            if not cfg.get("url"):
                raise ValueError("Remote MCP server requires a URL.")
            read, write = await stack.enter_async_context(sse_client(cfg["url"], headers=cls._build_headers(cfg)))
        else:
            raise ValueError(f"Unknown transport '{transport}'.")

        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    # -- tool introspection ------------------------------------------------
    @staticmethod
    def _serialize_tool(tool) -> Dict[str, Any]:
        schema = getattr(tool, "inputSchema", None) or {}
        return {
            "name": getattr(tool, "name", "unknown"),
            "description": (getattr(tool, "description", "") or "")[:400],
            "input_schema": schema,
        }

    @staticmethod
    def _cache_key(cfg: Dict[str, Any]) -> str:
        relevant = {k: cfg.get(k) for k in ("transport", "command", "args", "url", "auth_type", "header_name", "cwd")}
        return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()

    def list_tools(self, cfg: Dict[str, Any], use_cache: bool = True, timeout: float = 30.0) -> List[Dict[str, Any]]:
        key = self._cache_key(cfg)
        if use_cache:
            cached = self._tool_cache.get(key)
            if cached and (time.time() - cached[0]) < self._tool_cache_ttl:
                return cached[1]

        async def action(session):
            result = await session.list_tools()
            return [self._serialize_tool(t) for t in result.tools]

        tools = self.pool.call(cfg, action, timeout=timeout)
        self._tool_cache[key] = (time.time(), tools)
        return tools

    def test_server(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Connect to a server and return discovered tools (or an error).

        A successful manual test also closes any tripped circuit so the server
        immediately rejoins its assigned slots."""
        try:
            self.pool.breaker(cfg.get("id") or "").record_success()
            tools = self.list_tools(cfg, use_cache=False, timeout=30.0)
            return {"ok": True, "tools": tools, "tool_count": len(tools)}
        except concurrent.futures.TimeoutError:
            return {"ok": False, "error": "Connection timed out after 30s.", "tools": []}
        except Exception as e:
            return {"ok": False, "error": str(e), "tools": []}

    # -- tool invocation ---------------------------------------------------
    @staticmethod
    def _stringify_result(result) -> str:
        parts: List[str] = []
        for block in getattr(result, "content", []) or []:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(str(text))
            else:
                data = getattr(block, "data", None)
                if data is not None:
                    parts.append(f"[binary/{getattr(block, 'mimeType', 'data')} content]")
        out = "\n".join(parts).strip()
        if getattr(result, "isError", False):
            return f"[tool reported error] {out}"
        return out or "[tool returned no textual content]"

    def call_tool(
        self, server_id: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None, timeout: float = 45.0
    ) -> str:
        cfg = self.store.get(server_id)
        if not cfg:
            return f"Error: MCP server '{server_id}' is not configured."
        if not cfg.get("enabled", True):
            return f"Error: MCP server '{cfg.get('name', server_id)}' is disabled."

        args = arguments or {}

        async def action(session):
            result = await session.call_tool(tool_name, arguments=args)
            return self._stringify_result(result)

        try:
            return self.pool.call(cfg, action, timeout=timeout)
        except concurrent.futures.TimeoutError:
            return f"Error: MCP tool '{tool_name}' timed out after {timeout:.0f}s."
        except Exception as e:
            return f"Error calling MCP tool '{tool_name}' on '{cfg.get('name', server_id)}': {e}"

    # -- slot routing ------------------------------------------------------
    def servers_for_slot(self, slot: str) -> List[Dict[str, Any]]:
        out = []
        for cfg in self.store.list():
            if not cfg.get("enabled", True) or slot not in (cfg.get("assignments") or []):
                continue
            if self.pool.breaker(cfg["id"]).is_open:
                print(f"[MCP] Skipping '{cfg.get('name')}' for slot '{slot}': circuit open.")
                continue
            out.append(cfg)
        return out

    def tools_for_slot(self, slot: str) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Return (server_cfg, tool) pairs for every tool exposed to ``slot``."""
        pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for cfg in self.servers_for_slot(slot):
            try:
                for tool in self.list_tools(cfg, use_cache=True):
                    pairs.append((cfg, tool))
            except Exception as e:
                print(f"[MCP] Could not list tools for '{cfg.get('name')}': {e}")
        return pairs

    @staticmethod
    def _pick_lookup_tool(tools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        # Prefer tools by keyword priority (search/find/query rank above get/list).
        for kw in _LOOKUP_KEYWORDS:
            for tool in tools:
                if kw in (tool.get("name") or "").lower():
                    return tool
        return tools[0] if tools else None

    @staticmethod
    def _build_query_args(tool: Dict[str, Any], query: str) -> Dict[str, Any]:
        schema = tool.get("input_schema") or {}
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        args: Dict[str, Any] = {}
        # Prefer a well-known free-text query property.
        target = None
        for cand in _QUERY_PROP_NAMES:
            if cand in props:
                target = cand
                break
        if target is None and required:
            # Fall back to the first required string property.
            for r in required:
                if (props.get(r, {}) or {}).get("type", "string") == "string":
                    target = r
                    break
        if target is not None:
            args[target] = query
        return args

    def gather_context_for_slot(self, slot: str, query: str, max_chars: int = 1500) -> str:
        """Best-effort: query each MCP server assigned to ``slot`` and return text.

        Used to enrich individual pipeline prompts with external context. Failures
        are swallowed so the ingestion pipeline never breaks because of MCP issues.
        """
        servers = self.servers_for_slot(slot)
        if not servers or not query:
            return ""

        blocks: List[str] = []
        for cfg in servers:
            try:
                tools = self.list_tools(cfg, use_cache=True, timeout=20.0)
                tool = self._pick_lookup_tool(tools)
                if not tool:
                    continue
                args = self._build_query_args(tool, query)
                result = self.call_tool(cfg["id"], tool["name"], args, timeout=20.0)
                if result and not result.startswith("Error") and "[tool reported error]" not in result:
                    snippet = result[:max_chars]
                    blocks.append(f"[{cfg['name']} · {tool['name']}]\n{snippet}")
            except Exception as e:
                print(f"[MCP] enrichment for slot '{slot}' via '{cfg.get('name')}' failed: {e}")
        return "\n\n".join(blocks)


# Module-level singletons
mcp_store = MCPStore()
mcp_manager = MCPManager(mcp_store)
