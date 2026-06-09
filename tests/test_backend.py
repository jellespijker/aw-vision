import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Mock settings before importing config
os.environ["LANCE_DB_DIR"] = "/tmp/test_aw_vision_db"

from aw_vision.config import config  # noqa: E402
from aw_vision.db import db  # noqa: E402
from aw_vision.server import app  # noqa: E402

client = TestClient(app)


def test_config_defaults():
    """Verify config falls back to safe defaults and expands paths."""
    assert config.screenshot_interval == 60
    assert config.cpu_threshold == 80.0
    assert config.memory_threshold == 80.0
    assert "screenshots" in str(config.screenshots_dir)


def test_projects_loading(tmp_path):
    """Test loading and saving projects list."""
    test_projects_file = tmp_path / "test_projects.json"
    config.settings["projects_file"] = str(test_projects_file)

    test_data = [
        {
            "project_number": "PRJ-TEST",
            "description": "Test Project",
            "work_entailment": "Testing things.",
        }
    ]
    config.save_projects(test_data)

    loaded = config.load_projects()
    assert len(loaded) == 1
    assert loaded[0]["project_number"] == "PRJ-TEST"


def test_db_operations():
    """Test inserting and searching metadata records in LanceDB."""
    # Ensure table is initialized
    table = db.table
    assert table is not None

    # Delete any existing test record to make the test idempotent
    try:
        table.delete("id = 'test-uuid-123'")
    except Exception:
        pass

    # Insert a dummy record
    dummy_id = "test-uuid-123"
    dummy_record = {
        "id": dummy_id,
        "timestamp": 123456789.0,
        "image_path": "/tmp/test.png",
        "window_title": "Test Title",
        "app_name": "TestApp",
        "is_afk": False,
        "description": "This is a test description of a python file.",
        "tags": ["python", "test"],
        "project_number": "PRJ-TEST",
        "vector": [0.1] * db.get_embedding_dimension(),
    }

    db.insert_screenshot(dummy_record)

    # Query back
    records = db.query_metadata("id = 'test-uuid-123'")
    assert len(records) == 1
    assert records[0]["window_title"] == "Test Title"
    assert "python" in records[0]["tags"]


def test_fastapi_endpoints():
    """Test FastAPI core HTTP routes respond correctly."""
    # Status endpoint
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "watcher_running" in data
    assert "processor_running" in data
    assert "system_load" in data

    # Projects endpoint
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert "projects" in data
    assert "raw_stats" in data


def test_snapshot_reprocessing(tmp_path):
    """Test snapshot reprocessing API endpoint and database idempotency."""
    table = db.table
    assert table is not None

    test_id = "reprocess-test-uuid-456"
    try:
        table.delete(f"id = '{test_id}'")
    except Exception:
        pass

    # Create dummy processed image on disk
    processed_dir = config.screenshots_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    test_img = processed_dir / f"reprocess_test_{test_id}.png"
    test_img.write_text("dummy image content")

    dummy_record = {
        "id": test_id,
        "timestamp": 123456789.0,
        "image_path": str(test_img),
        "window_title": "Reprocess Window Title",
        "app_name": "ReprocessApp",
        "is_afk": False,
        "description": "Reprocess Description",
        "ocr_text": "Reprocess OCR Text",
        "tags": ["reprocess", "test"],
        "project_number": "PRJ-REPROCESS",
        "vector": [0.2] * db.get_embedding_dimension(),
    }

    # Test database insert (idempotent overwrite)
    db.insert_screenshot(dummy_record)
    # Insert again to verify idempotency delete works without raising errors
    db.insert_screenshot(dummy_record)

    # Call API to reprocess
    payload = {
        "ids": [test_id],
        "reprocess_ocr": False
    }
    resp = client.post("/api/reprocess", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["queued_count"] == 1
    assert data["skipped_count"] == 0

    # Verify that raw folder contains the copied image and the reconstructed JSON file
    raw_dir = config.screenshots_dir / "raw"
    copied_img = raw_dir / f"reprocess_test_{test_id}.png"
    reconstructed_json = raw_dir / f"reprocess_test_{test_id}.json"

    assert copied_img.exists()
    assert reconstructed_json.exists()

    with open(reconstructed_json, "r") as f:
        meta = json.load(f)
    assert meta["id"] == test_id
    assert meta["ocr_text"] == "Reprocess OCR Text"

    # Clean up files created
    copied_img.unlink()
    reconstructed_json.unlink()
    test_img.unlink()
    try:
        table.delete(f"id = '{test_id}'")
    except Exception:
        pass
