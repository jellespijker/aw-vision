"""Collectors adapting external providers into neutral ExternalEvents.

Three methods cover every provider without provider-specific code paths:

- ``git_local``: scans local repositories (zero network, zero auth) and
  derives project hints from branch/ref names — the strongest dev signal.
- ``command``: runs a whitelisted CLI (``gws`` for Google Workspace, ``gh``
  for GitHub, ``m365`` for Microsoft 365, ...) with time placeholders and
  hands the RAW output to the LLM normalizer.
- ``mcp``: calls a tool on any connected MCP server and normalizes likewise.

The normalizer is an editable prompt template ("context_normalizer" in
Settings → Prompts), so adapting a new provider's output shape is prompt
tuning, not code.
"""

import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from aw_vision.models import ExternalEvent

# CLIs a context source may execute. Extend deliberately (review required);
# each addition grants the journal read access to that provider's data.
COMMAND_WHITELIST = ("gws", "gh", "m365")

# Ticket/project keys like PRJ-2026-042 or EMB-467 inside branch names/titles.
PROJECT_KEY_RE = re.compile(r"\b[A-Z]{2,6}-(?:\d{4}-)?\d{1,5}(?=\D|$)")


def project_hint_from_text(text: str) -> str:
    keys = sorted(set(PROJECT_KEY_RE.findall(text or "")))
    return ", ".join(keys)


# ---------------------------------------------------------------------------
# git_local — built-in, no network
# ---------------------------------------------------------------------------


def _git_repos(root: Path, max_depth: int = 2) -> List[Path]:
    repos = []
    if (root / ".git").exists():
        return [root]
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if (child / ".git").exists():
            repos.append(child)
        elif max_depth > 1:
            repos.extend(_git_repos(child, max_depth - 1))
    return repos


def collect_git_local(source: Dict[str, Any], since_ts: float, until_ts: float) -> List[ExternalEvent]:
    """Commits across all local repos under repos_root, with branch-derived project hints."""
    root = Path(source.get("repos_root") or "~/dev").expanduser()
    if not root.is_dir():
        return []
    events: List[ExternalEvent] = []
    since_iso = datetime.fromtimestamp(since_ts).isoformat()
    until_iso = datetime.fromtimestamp(until_ts).isoformat()
    for repo in _git_repos(root)[:50]:
        try:
            res = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "log",
                    "--all",
                    f"--since={since_iso}",
                    f"--until={until_iso}",
                    "--format=%ct%x1f%an%x1f%s%x1f%D",
                ],
                capture_output=True,
                text=True,
                timeout=20.0,
                shell=False,
            )
            if res.returncode != 0:
                continue
            for line in res.stdout.splitlines():
                parts = line.split("\x1f")
                if len(parts) != 4:
                    continue
                ts, author, subject, refs = parts
                hint = project_hint_from_text(f"{refs} {subject}")
                events.append(
                    ExternalEvent(
                        source_id=source["id"],
                        kind="vcs",
                        provider="git",
                        start_ts=float(ts),
                        title=f"commit in {repo.name}: {subject[:120]}",
                        participants=[author] if author else [],
                        project_hint=hint or None,
                        summary=(refs or None),
                        collected_at=time.time(),
                    )
                )
        except Exception as e:
            print(f"[Journal] git scan failed for {repo}: {e}")
    return events


# ---------------------------------------------------------------------------
# command / mcp — provider output adapted by the LLM normalizer
# ---------------------------------------------------------------------------


def run_source_command(source: Dict[str, Any], since_ts: float, until_ts: float) -> str:
    """Execute the source's whitelisted CLI with time placeholders substituted."""
    binary = (source.get("command") or "").strip()
    if binary not in COMMAND_WHITELIST:
        raise ValueError(f"Command '{binary}' is not in the context-source whitelist {COMMAND_WHITELIST}.")
    if not shutil.which(binary):
        raise RuntimeError(f"CLI '{binary}' is not installed or not in PATH.")
    subs = {
        "{since_iso}": datetime.fromtimestamp(since_ts).isoformat(),
        "{until_iso}": datetime.fromtimestamp(until_ts).isoformat(),
        "{since_epoch}": str(int(since_ts)),
        "{until_epoch}": str(int(until_ts)),
    }
    args = [binary]
    for a in source.get("args") or []:
        for k, v in subs.items():
            a = a.replace(k, v)
        args.append(a)
    res = subprocess.run(args, capture_output=True, text=True, timeout=60.0, shell=False)
    if res.returncode != 0:
        raise RuntimeError(f"{binary} exited {res.returncode}: {(res.stderr or res.stdout)[:300]}")
    return (res.stdout or "").strip()


def normalize_with_llm(raw_output: str, source: Dict[str, Any]) -> List[ExternalEvent]:
    """Adapt arbitrary provider output into ExternalEvents via the editable prompt."""
    import requests

    from aw_vision.config import config
    from aw_vision.prompts import prompt_store, render_prompt
    from aw_vision.settings import settings_store
    from aw_vision.tooling import extract_json_object

    if not raw_output:
        return []
    prompt = render_prompt(
        prompt_store.get("context_normalizer"),
        {
            "kind": source.get("kind", "other"),
            "provider_label": source.get("provider_label") or source.get("name", ""),
            "raw_output": raw_output[:12000],
        },
    )
    resp = requests.post(
        f"{config.ollama_host}/api/generate",
        json={
            "model": config.vision_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_ctx": settings_store.get_int("ollama_context_size") or 8192},
            "keep_alive": 0,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    parsed = json.loads(extract_json_object(resp.json().get("response", "")))
    events = []
    for item in parsed.get("events", []) if isinstance(parsed, dict) else []:
        try:
            title = str(item.get("title") or "").strip()
            start = float(item.get("start_ts") or 0.0)
            if not title or start <= 0:
                continue
            events.append(
                ExternalEvent(
                    source_id=source["id"],
                    kind=source.get("kind", "other"),
                    provider=source.get("provider_label") or source.get("method", ""),
                    start_ts=start,
                    end_ts=float(item["end_ts"]) if item.get("end_ts") else None,
                    title=title[:200],
                    participants=[str(x) for x in (item.get("participants") or [])][:20],
                    project_hint=project_hint_from_text(f"{title} {item.get('project_hint') or ''}") or None,
                    summary=(str(item.get("summary") or "").strip() or None),
                    collected_at=time.time(),
                )
            )
        except Exception:
            continue
    return events


def collect_command(source: Dict[str, Any], since_ts: float, until_ts: float) -> List[ExternalEvent]:
    return normalize_with_llm(run_source_command(source, since_ts, until_ts), source)


def collect_mcp(source: Dict[str, Any], since_ts: float, until_ts: float) -> List[ExternalEvent]:
    from aw_vision.mcp_manager import mcp_manager

    args = dict(source.get("mcp_args") or {})
    for k, v in list(args.items()):
        if isinstance(v, str):
            v = v.replace("{since_iso}", datetime.fromtimestamp(since_ts).isoformat())
            v = v.replace("{until_iso}", datetime.fromtimestamp(until_ts).isoformat())
            args[k] = v
    raw = mcp_manager.call_tool(source["mcp_server_id"], source["mcp_tool"], args, timeout=60.0)
    if raw.startswith("Error"):
        raise RuntimeError(raw[:300])
    return normalize_with_llm(raw, source)


def collect_for_source(source: Dict[str, Any], since_ts: float, until_ts: float) -> List[ExternalEvent]:
    method = source.get("method")
    if method == "git_local":
        return collect_git_local(source, since_ts, until_ts)
    if method == "command":
        return collect_command(source, since_ts, until_ts)
    if method == "mcp":
        return collect_mcp(source, since_ts, until_ts)
    raise ValueError(f"Unknown context-source method '{method}'.")
