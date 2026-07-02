"""Tests for contiguous same-app session-block resolution."""

import os
import time

os.environ.setdefault("LANCE_DB_DIR", "/tmp/test_aw_vision_db")

from aw_vision.db import db  # noqa: E402


def _rec(rid: str, ts: float, app: str) -> dict:
    dim = db.get_embedding_dimension()
    return {
        "id": rid,
        "timestamp": ts,
        "image_path": None,
        "window_title": f"win-{rid}",
        "app_name": app,
        "is_afk": False,
        "description": f"desc-{rid}",
        "ocr_text": None,
        "tags": [],
        "project_number": None,
        "human_labeled": False,
        "unique_things": None,
        "vector": [0.0] * dim,
    }


def test_get_session_block_walks_contiguous_same_app_chain():
    base = time.time() - 86400 * 30  # park test records well in the past
    ids = []
    try:
        # Chain: three konsole shots 60s apart, a 30-min gap, then another konsole
        # shot, plus an interleaved firefox shot that must never join the block.
        for rid, offset, app in [
            ("sess-a", 0, "konsole-test"),
            ("sess-b", 60, "konsole-test"),
            ("sess-c", 120, "konsole-test"),
            ("sess-d", 120 + 1800, "konsole-test"),
            ("sess-x", 90, "firefox-test"),
        ]:
            db.insert_screenshot(_rec(rid, base + offset, app))
            ids.append(rid)

        block = db.get_session_block("sess-b", max_gap_seconds=900)
        block_ids = [r["id"] for r in block]
        assert block_ids == ["sess-a", "sess-b", "sess-c"]

        # The far-side record forms its own block.
        lone = db.get_session_block("sess-d", max_gap_seconds=900)
        assert [r["id"] for r in lone] == ["sess-d"]

        # Unknown record yields empty.
        assert db.get_session_block("sess-nope") == []
    finally:
        for rid in ids:
            try:
                db.table.delete(f"id = '{rid}'")
            except Exception:
                pass
