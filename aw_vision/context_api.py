"""API routes for the external context journal (sources + events)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/context")


class ContextSourceModel(BaseModel):
    id: Optional[str] = None
    name: str
    kind: str = "other"
    provider_label: Optional[str] = ""
    method: str = "command"
    enabled: bool = False
    repos_root: Optional[str] = ""
    command: Optional[str] = ""
    args: Optional[List[str]] = None
    mcp_server_id: Optional[str] = ""
    mcp_tool: Optional[str] = ""
    mcp_args: Optional[Dict[str, Any]] = None
    schedule_minutes: int = 60
    lookback_minutes: int = 180


@router.get("/sources")
def list_sources():
    """All configured context sources with their last run/error state."""
    from aw_vision.context_journal import context_source_store

    return {"sources": context_source_store.list()}


@router.post("/sources")
def save_source(payload: ContextSourceModel):
    """Create or update a context source (Google, Microsoft, git — any provider)."""
    from aw_vision.context_collectors import COMMAND_WHITELIST
    from aw_vision.context_journal import context_source_store

    data = payload.dict(exclude_none=False)
    if data.get("method") == "command" and (data.get("command") or "") not in COMMAND_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=f"Command must be one of the whitelisted CLIs: {', '.join(COMMAND_WHITELIST)}.",
        )
    return {"status": "success", "source": context_source_store.save(data)}


@router.delete("/sources/{source_id}")
def delete_source(source_id: str):
    from aw_vision.context_journal import context_source_store

    if not context_source_store.delete(source_id):
        raise HTTPException(status_code=404, detail="Context source not found.")
    return {"status": "success"}


@router.post("/collect")
def collect_now():
    """Run collection for every enabled source immediately (ignores schedules)."""
    from aw_vision.context_journal import context_journal, context_source_store

    for source in context_source_store.list():
        if source.get("enabled"):
            source["last_run"] = 0.0
            context_source_store.save(source)
    return {"status": "success", "report": context_journal.run_collection()}


@router.get("/events")
def recent_events(around_ts: Optional[float] = None, window: float = 1800.0):
    """Journal events around a timestamp (defaults to now) — the same view the prompts get."""
    import time

    from aw_vision.context_journal import context_journal

    ts = around_ts or time.time()
    return {"events": context_journal.events_around(ts, window=window)}
