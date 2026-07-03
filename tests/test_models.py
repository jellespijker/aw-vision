"""Tests for the shared typed Snapshot record."""

import os

os.environ.setdefault("LANCE_DB_DIR", "/tmp/test_aw_vision_db")

from aw_vision.models import Snapshot  # noqa: E402


def test_from_lance_tolerates_missing_and_extra_columns():
    row = {
        "id": "abc",
        "timestamp": 1.5,
        "image_path": "/data/processed/shot.png",
        "window_title": "t",
        "app_name": "konsole",
        "vector": [0.0] * 8,  # extra column must be ignored
        "unknown_future_column": "x",
        "people": ["Casper Lambo"],
    }
    snap = Snapshot.from_lance(row)
    assert snap.id == "abc"
    assert snap.people == ["Casper Lambo"]
    assert snap.tags == []  # missing column defaults


def test_to_api_shape_and_filename_reduction():
    snap = Snapshot(id="abc", image_path="/data/processed/shot.png", human_labeled=True)
    payload = snap.to_api(distance=0.42)
    assert payload["image_filename"] == "shot.png"
    assert payload["is_processed"] is True
    assert payload["distance"] == 0.42
    assert payload["human_labeled"] is True
    # Every frontend HistoryRecord field must be present
    for key in (
        "ocr_text",
        "tags",
        "project_number",
        "unique_things",
        "user_context",
        "analysis_reasoning",
        "classification_confidence",
        "people",
    ):
        assert key in payload

    pending = Snapshot.from_pending_meta({"id": "p1", "timestamp": 2.0, "user_context": "note"}, "raw.png")
    p = pending.to_api(is_processed=False, description_override="Pending processing...")
    assert p["description"] == "Pending processing..."
    assert p["is_processed"] is False
    assert p["user_context"] == "note"


def test_to_lance_normalizes_none_project_and_attaches_vector():
    snap = Snapshot(id="abc", project_number="None")
    rec = snap.to_lance([0.1, 0.2])
    assert rec["project_number"] is None
    assert rec["vector"] == [0.1, 0.2]
    assert rec["id"] == "abc"
