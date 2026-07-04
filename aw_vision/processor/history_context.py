"""Historical/temporal context assembly shared by the analysis prompts.

Previously processed snapshots are the strongest signal for keeping
classification, tags and terminology consistent over time. This module turns
them into ready-to-inject prompt blocks used by BOTH the local two-pass
pipeline and the combined Gemini call, so cloud and local analysis reason over
the same evidence.
"""

import json
import time
from typing import Any, Dict

from aw_vision.db import db


def build_aw_context(meta: Dict[str, Any]) -> str:
    """ActivityWatch bucket state captured alongside the screenshot."""
    bucket_context = meta.get("aw_bucket_context") or {}
    if not bucket_context:
        return "None"
    return json.dumps(bucket_context, indent=2, ensure_ascii=False)


def _format_neighbor(label: str, rec: Dict[str, Any]) -> str:
    proj = rec.get("project_number") or "None"
    human = "Yes (Verified)" if rec.get("human_labeled") else "No (Auto-classified)"
    return f"""- {label}:
  * Application: {rec.get('app_name', 'Unknown')}
  * Window Title: {rec.get('window_title', 'Unknown')}
  * Description: {rec.get('description', 'No description')}
  * Project Assigned: {proj}
  * Label Is Verified by Human: {human}
"""


def build_neighbor_context(timestamp: float) -> str:
    """The chronologically adjacent processed snapshots around ``timestamp``."""
    out = ""
    past = db.get_past_neighbor(timestamp)
    if past:
        out += _format_neighbor("PRECEDING SNAPSHOT (Past Neighbor)", past)
    future = db.get_future_neighbor(timestamp)
    if future:
        out += _format_neighbor("SUCCEEDING SNAPSHOT (Future Neighbor)", future)
    return out or "- No chronological neighbor snapshots are currently available."


def build_app_frequency_context(app_name: str) -> str:
    """Historical project associations for this application, weighted by human labels."""
    app_freqs = db.get_app_project_frequencies(app_name)
    if not app_freqs:
        return f"  * No historical project associations for '{app_name}'."
    return "\n".join(f"  * Project {proj}: score {freq:.1f}" for proj, freq in app_freqs.items())


def build_similar_snapshots_context(app_name: str, window_title: str, limit: int = 5) -> str:
    """Previously labeled snapshots with matching app/title metadata (no ML models loaded)."""
    similar = db.get_similar_labeled_snapshots_by_metadata(app_name=app_name, window_title=window_title, limit=limit)
    return json.dumps(similar, ensure_ascii=False)


def build_previous_snapshot_block(timestamp: float) -> str:
    """A light continuity block for the vision pass: what the previous snapshot showed."""
    past = db.get_past_neighbor(timestamp)
    if not past:
        return ""
    desc = (past.get("description") or "").strip()
    if not desc:
        return ""
    age = ""
    try:
        delta = timestamp - float(past.get("timestamp", 0.0))
        if 0 < delta < 3600:
            age = f", captured ~{int(delta)}s earlier"
    except Exception:
        pass
    return (
        f"TEMPORAL CONTINUITY: the previously processed snapshot (application "
        f"\"{past.get('app_name', 'Unknown')}\", window \"{past.get('window_title', 'Unknown')}\"{age}) "
        f'was described as: "{desc}". If this screenshot clearly continues the same activity, keep '
        "file names and terminology consistent with it — but describe what THIS screenshot shows; never "
        "copy the previous description blindly.\n\n"
    )


def build_history_context(meta: Dict[str, Any]) -> Dict[str, str]:
    """All historical prompt blocks for one screenshot's metadata, ready for render_prompt."""
    timestamp = float(meta.get("timestamp", time.time()))
    app_name = meta.get("app_name", "Unknown")
    window_title = meta.get("window_title", "")
    external = ""
    likelihood_block = ""
    try:
        from aw_vision.context_journal import context_journal

        events = context_journal.events_around(timestamp)
        external = context_journal.build_external_events_block(timestamp)
    except Exception as e:
        events = []
        print(f"[Journal] external-events block failed: {e}")
    try:
        from aw_vision.config import config
        from aw_vision.project_likelihood import (
            evidence_model,
            format_likelihood_block,
            signal_projects_from_events,
        )

        catalog = [p.get("project_number") for p in config.load_projects()]
        prior = evidence_model.score(
            app_name=app_name,
            window_title=window_title,
            signal_projects=signal_projects_from_events(events, catalog),
        )
        likelihood_block = format_likelihood_block(prior)
    except Exception as e:
        print(f"[Likelihood] prior computation failed: {e}")
    return {
        "external_events": external,
        "project_likelihoods": likelihood_block,
        "aw_context": build_aw_context(meta),
        "neighbor_context": build_neighbor_context(timestamp),
        "similar_snapshots": build_similar_snapshots_context(app_name, window_title),
        "app_frequencies": build_app_frequency_context(app_name),
        "previous_snapshot_block": build_previous_snapshot_block(timestamp),
    }
