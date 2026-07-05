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
    print("ENV LANCE_DB_DIR:", os.environ.get("LANCE_DB_DIR"))
    print("CONFIG DB DIR:", config.db_dir)
    from aw_vision.settings import settings_store
    print("SETTINGS STORE KV TABLE:", settings_store._kv.table_name)
    print("SETTINGS STORE CACHE:", settings_store._cache)
    print("SETTINGS INTERVAL SECONDS:", settings_store.get("screenshot_interval_seconds"))
    assert config.screenshot_interval == 60
    assert config.cpu_threshold == 80.0
    assert config.memory_threshold == 90.0
    assert "screenshots" in str(config.screenshots_dir)


def test_projects_loading(tmp_path):
    """Test loading and saving projects list."""
    try:
        db.delete_project("PRJ-TEST")
    except Exception:
        pass

    test_data = [
        {
            "project_number": "PRJ-TEST",
            "description": "Test Project",
            "work_entailment": "Testing things.",
        }
    ]
    config.save_projects(test_data)

    loaded = config.load_projects()
    saved = next((p for p in loaded if p["project_number"] == "PRJ-TEST"), None)
    assert saved is not None
    assert saved["description"] == "Test Project"

    # Clean up
    try:
        db.delete_project("PRJ-TEST")
    except Exception:
        pass


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


def test_summarize_ocr_text():
    """Verify that summarize_ocr_text correctly cleans and truncates OCR outputs in Caveman style."""
    from aw_vision.processor import processor

    # Case 1: Empty text
    assert processor.summarize_ocr_text("") == ""
    assert processor.summarize_ocr_text(None) == ""

    # Case 2: Clean, remove filler words, and filter consecutive redundant lines
    dirty_text = "The Line 1\n\n  \nThe Line 1\nLine 2 and an or\nLine 1\n"
    # Expected: "Line 1 | Line 2" (because "The", "and", "an", "or" are filler words)
    cleaned = processor.summarize_ocr_text(dirty_text)
    assert "Line 1" in cleaned
    assert "Line 2" in cleaned
    # Check that there are no empty elements or whitespace issues
    lines = [line_str.strip() for line_str in cleaned.split("|") if "truncated" not in line_str]
    assert len(lines) == 2
    assert lines[0] == "Line 1"
    assert lines[1] == "Line 2"

    # Case 3: Truncation behavior
    long_text = "\n".join([f"This is sentence line {i}" for i in range(100)])
    max_chars = 200
    truncated = processor.summarize_ocr_text(long_text, max_chars=max_chars)
    assert len(truncated) > 0
    assert "lines omitted" in truncated
    assert len(truncated) <= max_chars


def test_get_binned_timeline():
    """Verify that get_binned_timeline correctly aggregates active durations by resolution and excludes AFK."""
    table = db.table
    assert table is not None

    test_ids = [
        "timeline-test-1",
        "timeline-test-2",
        "timeline-test-3",
        "timeline-test-4",
    ]
    for tid in test_ids:
        try:
            table.delete(f"id = '{tid}'")
        except Exception:
            pass

    # Setup base times aligned to hours
    base_time = 1699999200.0  # Aligned start timestamp (perfectly divisible by 3600)

    # Insert mock records
    # PRJ-A has active records in Hour 0
    r1 = {
        "id": "timeline-test-1",
        "timestamp": base_time,
        "image_path": "/tmp/test.png",
        "window_title": "Active Proj A",
        "app_name": "Editor",
        "is_afk": False,
        "description": "Active Proj A record",
        "project_number": "PRJ-A",
        "vector": [0.1] * db.get_embedding_dimension(),
    }
    r2 = {
        "id": "timeline-test-2",
        "timestamp": base_time + 60.0,
        "image_path": "/tmp/test.png",
        "window_title": "Active Proj A 2",
        "app_name": "Editor",
        "is_afk": False,
        "description": "Active Proj A record 2",
        "project_number": "PRJ-A",
        "vector": [0.1] * db.get_embedding_dimension(),
    }
    # PRJ-B has active record in Hour 1
    r3 = {
        "id": "timeline-test-3",
        "timestamp": base_time + 3600.0,
        "image_path": "/tmp/test.png",
        "window_title": "Active Proj B",
        "app_name": "Slack",
        "is_afk": False,
        "description": "Active Proj B record",
        "project_number": "PRJ-B",
        "vector": [0.1] * db.get_embedding_dimension(),
    }
    # PRJ-A has AFK record in Hour 0 (should be excluded)
    r4 = {
        "id": "timeline-test-4",
        "timestamp": base_time + 120.0,
        "image_path": "/tmp/test.png",
        "window_title": "AFK Proj A",
        "app_name": "None",
        "is_afk": True,
        "description": "AFK Proj A record",
        "project_number": "PRJ-A",
        "vector": [0.1] * db.get_embedding_dimension(),
    }

    try:
        db.insert_screenshot(r1)
        db.insert_screenshot(r2)
        db.insert_screenshot(r3)
        db.insert_screenshot(r4)

        # Get binned timeline: range is base_time to base_time + 7200.0, resolution 1 hour (3600.0s)
        start_t = base_time
        end_t = base_time + 7200.0
        res = db.get_binned_timeline(start_t, end_t, 3600.0)

        assert res["aligned_start"] == base_time
        assert res["num_bins"] == 3  # covers index 0, 1, 2

        # Verify PRJ-A has active duration of 120s (r1, r2) in bin 0, 0 in bin 1 & 2
        assert "PRJ-A" in res["projects"]
        prj_a_bins = res["projects"]["PRJ-A"]
        assert len(prj_a_bins) == 3
        assert prj_a_bins[0]["duration_seconds"] == 120.0
        assert prj_a_bins[1]["duration_seconds"] == 0.0
        assert prj_a_bins[2]["duration_seconds"] == 0.0

        # Verify PRJ-B has active duration of 60s (r3) in bin 1, 0 in bin 0 & 2
        assert "PRJ-B" in res["projects"]
        prj_b_bins = res["projects"]["PRJ-B"]
        assert len(prj_b_bins) == 3
        assert prj_b_bins[0]["duration_seconds"] == 0.0
        assert prj_b_bins[1]["duration_seconds"] == 60.0
        assert prj_b_bins[2]["duration_seconds"] == 0.0

        # Verify Unclassified has 0s duration across all bins
        assert "Unclassified" in res["projects"]
        un_bins = res["projects"]["Unclassified"]
        assert len(un_bins) == 3
        assert all(b["duration_seconds"] == 0.0 for b in un_bins)

    finally:
        for tid in test_ids:
            try:
                table.delete(f"id = '{tid}'")
            except Exception:
                pass


def test_get_projects_timeline_api():
    """Verify that the FastAPI timeline endpoint responds correctly and processes query params."""
    table = db.table
    assert table is not None

    test_ids = ["timeline-api-test-1"]
    for tid in test_ids:
        try:
            table.delete(f"id = '{tid}'")
        except Exception:
            pass

    base_time = 1699999200.0
    r = {
        "id": "timeline-api-test-1",
        "timestamp": base_time + 10.0,
        "image_path": "/tmp/test.png",
        "window_title": "API Proj C",
        "app_name": "Terminal",
        "is_afk": False,
        "description": "API test record",
        "project_number": "PRJ-C",
        "vector": [0.1] * db.get_embedding_dimension(),
    }

    try:
        db.insert_screenshot(r)

        # Call the endpoint
        resp = client.get(f"/api/projects/timeline?start_time={base_time}&end_time={base_time + 3600.0}&resolution=1h")
        assert resp.status_code == 200

        data = resp.json()
        assert "projects" in data
        assert "timeline_headers" in data
        assert len(data["timeline_headers"]) == 2  # base_time and base_time + 3600

        # Verify project list contains PRJ-C with matching duration and dynamic color
        prj_c = next((p for p in data["projects"] if p["project_number"] == "PRJ-C"), None)
        assert prj_c is not None
        assert prj_c["total_duration_seconds"] == 60.0
        assert prj_c["color"].startswith("hsl(")

    finally:
        for tid in test_ids:
            try:
                table.delete(f"id = '{tid}'")
            except Exception:
                pass


def test_project_crud_endpoints():
    """Verify delete, save/add single project, and toggle-active endpoints."""
    # 1. Add/Save a project
    new_project = {
        "project_number": "PRJ-ENDPOINT-TEST",
        "description": "Endpoint CRUD verification",
        "work_entailment": "Running unit tests",
        "is_active": True
    }
    resp = client.post("/api/projects", json=new_project)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # 2. Toggle active state
    resp = client.patch("/api/projects/PRJ-ENDPOINT-TEST/toggle-active")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["is_active"] is False

    # 3. Retrieve projects and confirm it is present and inactive
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json()["projects"]
    saved_proj = next((p for p in projects if p["project_number"] == "PRJ-ENDPOINT-TEST"), None)
    assert saved_proj is not None
    assert saved_proj["is_active"] is False

    # 4. Toggle active back to True
    resp = client.patch("/api/projects/PRJ-ENDPOINT-TEST/toggle-active")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    # 5. Delete project
    resp = client.delete("/api/projects/PRJ-ENDPOINT-TEST")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # 6. Retrieve projects and confirm it is gone
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json()["projects"]
    deleted_proj = next((p for p in projects if p["project_number"] == "PRJ-ENDPOINT-TEST"), None)
    assert deleted_proj is None
