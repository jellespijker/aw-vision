"""Provider-agnostic external context journal.

Calendars, mail, chat and version-control activity are near-ground-truth for
"what was actually being worked on", but none of it appears reliably on
screen. This journal collects such events into a NEUTRAL schema so the
analysis prompts can cite them as evidence — replayable for reprocessing
(live lookups would return *today's* calendar for last month's snapshot).

Provider-agnosticism is deliberate and three-fold:
1. ``ExternalEvent`` is neutral — nothing Google/Microsoft-specific.
2. Sources are defined by METHOD, not provider: ``git_local`` (built-in),
   ``command`` (any whitelisted CLI: gws, gh, m365, ...) or ``mcp`` (any
   connected MCP server tool).
3. Raw provider output is adapted by an editable LLM normalizer prompt
   (Settings → Prompts), so a Microsoft user configures a source with their
   CLI/MCP and the same machinery produces the same events.
"""

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from aw_vision.config import config
from aw_vision.kvstore import LanceKVStore
from aw_vision.models import ExternalEvent

VALID_KINDS = ("calendar", "mail", "chat", "vcs", "other")
VALID_METHODS = ("git_local", "command", "mcp")

# How far around a snapshot timestamp events count as concurrent evidence.
EVENT_WINDOW_SECONDS = 1800.0


def normalize_source(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce an arbitrary incoming dict into a fully-formed source config."""
    kind = (raw.get("kind") or "other").lower()
    method = (raw.get("method") or "command").lower()
    return {
        "id": raw.get("id") or uuid.uuid4().hex[:12],
        "name": (raw.get("name") or "Unnamed Source").strip(),
        "kind": kind if kind in VALID_KINDS else "other",
        "provider_label": (raw.get("provider_label") or "").strip(),
        "method": method if method in VALID_METHODS else "command",
        "enabled": bool(raw.get("enabled", False)),
        # git_local
        "repos_root": (raw.get("repos_root") or "").strip(),
        # command: {since_iso}/{until_iso} placeholders are substituted per run
        "command": (raw.get("command") or "").strip(),
        "args": [str(a) for a in (raw.get("args") or [])],
        # mcp
        "mcp_server_id": (raw.get("mcp_server_id") or "").strip(),
        "mcp_tool": (raw.get("mcp_tool") or "").strip(),
        "mcp_args": raw.get("mcp_args") if isinstance(raw.get("mcp_args"), dict) else {},
        # scheduling
        "schedule_minutes": max(5, int(raw.get("schedule_minutes") or 60)),
        "lookback_minutes": max(15, int(raw.get("lookback_minutes") or 180)),
        "last_run": float(raw.get("last_run") or 0.0),
        "last_error": (raw.get("last_error") or "")[:300],
    }


class ContextSourceStore:
    """Persist context-source configs (LanceKVStore id/blob rows)."""

    def __init__(self):
        self._kv = LanceKVStore("context_sources", key_field="id", value_field="blob")
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.load_all()

    def load_all(self):
        self._cache = {}
        for row_id, blob in self._kv.items(limit=200).items():
            try:
                data = json.loads(blob)
                if data and data.get("id"):
                    self._cache[data["id"]] = normalize_source(data)
            except Exception as e:
                print(f"[Journal] Warning: could not decode context source {row_id}: {e}")
        if not self._cache:
            self._seed_defaults()

    def _seed_defaults(self):
        """Example sources (disabled — journal collection is strictly opt-in)."""
        self.save(
            {
                "id": "git_local",
                "name": "Local git repositories",
                "kind": "vcs",
                "provider_label": "git",
                "method": "git_local",
                "repos_root": "~/dev",
                "schedule_minutes": 30,
                "enabled": False,
            }
        )

    def list(self) -> List[Dict[str, Any]]:
        return [dict(v) for v in self._cache.values()]

    def get(self, source_id: str) -> Optional[Dict[str, Any]]:
        cfg = self._cache.get(source_id)
        return dict(cfg) if cfg else None

    def save(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        cfg = normalize_source(raw)
        self._cache[cfg["id"]] = cfg
        self._kv.upsert(cfg["id"], json.dumps(cfg, ensure_ascii=False))
        return cfg

    def delete(self, source_id: str) -> bool:
        existed = source_id in self._cache
        self._cache.pop(source_id, None)
        self._kv.delete(source_id)
        return existed


class ContextJournal:
    """The external_events table plus collection scheduling and prompt rendering."""

    def __init__(self, store: ContextSourceStore):
        self.store = store
        self._db_conn = None
        self._table = None
        self.table_name = "external_events"

    @property
    def table(self):
        if self._table is None:
            import lancedb
            import pyarrow as pa

            conn = self._db_conn or lancedb.connect(config.db_dir)
            self._db_conn = conn
            if self.table_name in conn.table_names():
                self._table = conn.open_table(self.table_name)
            else:
                schema = pa.schema(
                    [
                        pa.field("id", pa.string(), nullable=False),
                        pa.field("source_id", pa.string(), nullable=True),
                        pa.field("kind", pa.string(), nullable=True),
                        pa.field("provider", pa.string(), nullable=True),
                        pa.field("start_ts", pa.float64(), nullable=False),
                        pa.field("end_ts", pa.float64(), nullable=True),
                        pa.field("title", pa.string(), nullable=True),
                        pa.field("participants", pa.list_(pa.string()), nullable=True),
                        pa.field("project_hint", pa.string(), nullable=True),
                        pa.field("summary", pa.string(), nullable=True),
                        pa.field("collected_at", pa.float64(), nullable=True),
                    ]
                )
                self._table = conn.create_table(self.table_name, schema=schema)
        return self._table

    @staticmethod
    def event_id(source_id: str, title: str, start_ts: float) -> str:
        return hashlib.sha256(f"{source_id}|{title}|{start_ts:.0f}".encode()).hexdigest()[:24]

    def insert_events(self, events: List[ExternalEvent]) -> int:
        """Idempotently insert events (dedup by deterministic id)."""
        if not events:
            return 0
        rows = []
        for ev in events:
            row = ev.model_dump()
            row["id"] = row.get("id") or self.event_id(ev.source_id, ev.title, ev.start_ts)
            rows.append(row)
        tbl = self.table
        for row in rows:
            try:
                tbl.delete(f"id = '{row['id']}'")
            except Exception:
                pass
        tbl.add(rows)
        return len(rows)

    def events_around(self, timestamp: float, window: float = EVENT_WINDOW_SECONDS) -> List[Dict[str, Any]]:
        """Events overlapping [timestamp - window, timestamp + window], newest first."""
        try:
            lo, hi = timestamp - window, timestamp + window
            where = f"start_ts <= {hi} AND (end_ts >= {lo} OR (end_ts IS NULL AND start_ts >= {lo}))"
            rows = self.table.search().where(where).limit(50).to_list()
            rows.sort(key=lambda r: r.get("start_ts", 0.0), reverse=True)
            return rows[:12]
        except Exception as e:
            print(f"[Journal] Query failed: {e}")
            return []

    def build_external_events_block(self, timestamp: float) -> str:
        """Prompt-ready evidence block for one snapshot timestamp ("" when empty)."""
        from datetime import datetime

        rows = self.events_around(timestamp)
        if not rows:
            return ""
        lines = [
            "CONCURRENT EXTERNAL EVENTS (from the user's calendar/mail/chat/version-control "
            "journal; strong evidence for what was actually being worked on — ranked just "
            "below the user's own note):"
        ]
        for r in rows:
            start = datetime.fromtimestamp(r.get("start_ts", 0.0)).strftime("%H:%M")
            parts = ", ".join(r.get("participants") or [])
            line = f"- [{r.get('kind', 'other')}/{r.get('provider', '?')} {start}] {r.get('title', '')}"
            if r.get("project_hint"):
                line += f" | PROJECT SIGNAL: {r['project_hint']}"
            if parts:
                line += f" | with: {parts}"
            if r.get("summary"):
                line += f" | {r['summary'][:160]}"
            lines.append(line)
        return "\n".join(lines) + "\n\n"

    def run_collection(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Collect from every enabled source whose schedule elapsed. Never raises."""
        from aw_vision.context_collectors import collect_for_source

        now = now or time.time()
        report: Dict[str, Any] = {}
        for source in self.store.list():
            if not source.get("enabled"):
                continue
            if now - source.get("last_run", 0.0) < source["schedule_minutes"] * 60:
                continue
            since = now - source["lookback_minutes"] * 60
            try:
                events = collect_for_source(source, since, now)
                count = self.insert_events(events)
                source["last_run"] = now
                source["last_error"] = ""
                report[source["id"]] = {"ok": True, "events": count}
            except Exception as e:
                source["last_run"] = now
                source["last_error"] = str(e)[:300]
                report[source["id"]] = {"ok": False, "error": str(e)[:300]}
                print(f"[Journal] Collection failed for '{source.get('name')}': {e}")
            self.store.save(source)
        return report


context_source_store = ContextSourceStore()
context_journal = ContextJournal(context_source_store)
