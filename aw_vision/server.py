import os
from pathlib import Path
from typing import List, Optional

import psutil
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aw_vision.agent import AIMessage, HumanMessage, agent_app
from aw_vision.config import config
from aw_vision.db import db
from aw_vision.processor import processor
from aw_vision.watcher import watcher

# Initialize FastAPI App
app = FastAPI(
    title="aw-vision API",
    description="Backend services for visual and semantic desktop tracking.",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Lifecycle Events
# ---------------------------------------------------------


@app.on_event("startup")
def startup_event():
    print("Starting aw-vision services...")
    # Start background threads
    watcher.start()
    processor.start()


@app.on_event("shutdown")
def shutdown_event():
    print("Stopping aw-vision services...")
    watcher.stop()
    processor.stop()


# ---------------------------------------------------------
# Models
# ---------------------------------------------------------


class QueryRequest(BaseModel):
    prompt: str
    history: Optional[List[dict]] = []


class ProjectModel(BaseModel):
    project_number: str
    description: str
    work_entailment: str


class LabelRequest(BaseModel):
    project_number: Optional[str] = None


class ReprocessRequest(BaseModel):
    ids: Optional[List[str]] = None
    limit: Optional[int] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    reprocess_ocr: bool = False
    all: bool = False


class SettingsUpdateRequest(BaseModel):
    settings: dict


class TestKeyRequest(BaseModel):
    api_key: str


# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------


@app.get("/api/status")
def get_status():
    """Get system health, background daemon statuses, and verify active external dependencies (aw-server, Ollama, Capture CLI)."""
    import shutil
    import requests

    try:
        pending_count = len(processor.get_pending_queue())
    except Exception:
        pending_count = 0

    try:
        total_records = len(db.get_all_records(limit=100000))
    except Exception:
        total_records = 0

    # Check if aw-server is online on port 5600
    aw_server_online = False
    try:
        resp = requests.get("http://127.0.0.1:5600/api/0/buckets", timeout=1.0)
        if resp.status_code == 200:
            aw_server_online = True
    except Exception:
        pass

    # Check if Ollama is online
    ollama_online = False
    try:
        resp = requests.get(f"{config.ollama_host}/api/tags", timeout=1.0)
        if resp.status_code == 200:
            ollama_online = True
    except Exception:
        pass

    # Check if capture tools are on system PATH
    spectacle_available = bool(shutil.which("spectacle"))
    grim_available = bool(shutil.which("grim"))
    capture_cli_available = spectacle_available or grim_available

    return {
        "watcher_running": watcher.running,
        "processor_running": processor.running,
        "pending_queue_size": pending_count,
        "processed_database_size": total_records,
        "processing_ids": list(processor.processing_ids),
        "system_load": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
        },
        "aw_server_online": aw_server_online,
        "ollama_online": ollama_online,
        "capture_cli_available": capture_cli_available,
        "capture_cli_details": {
            "spectacle": spectacle_available,
            "grim": grim_available,
        }
    }


@app.post("/api/query")
def post_query(request: QueryRequest):
    """Run conversational queries using the LangGraph ReAct Agent."""
    prompt = request.prompt
    history = request.history or []

    # Map request history into LangChain messages
    messages = []
    for h in history:
        role = h.get("role")
        content = h.get("content")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))

    # Append current prompt
    messages.append(HumanMessage(content=prompt))

    try:
        # Run state graph
        inputs = {"messages": messages}
        output = agent_app.invoke(inputs)

        # Extract last assistant message
        final_messages = output.get("messages", [])
        if final_messages:
            last_msg = final_messages[-1]
            return {
                "response": last_msg.content,
                "history": [
                    {
                        "role": "user" if isinstance(m, HumanMessage) else "assistant",
                        "content": m.content,
                    }
                    for m in final_messages
                    if isinstance(m, (HumanMessage, AIMessage))
                ],
            }
        else:
            raise HTTPException(status_code=500, detail="No reply returned by agent graph.")

    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Agent graph execution error: {e}")


@app.get("/api/screenshots/{filename}")
def get_screenshot(filename: str):
    """Serve processed screenshots statically."""
    processed_dir = config.screenshots_dir / "processed"
    file_path = processed_dir / filename

    if not file_path.exists():
        # Fallback check raw
        raw_path = config.screenshots_dir / "raw" / filename
        if raw_path.exists():
            return FileResponse(raw_path)
        raise HTTPException(status_code=404, detail="Screenshot not found.")

    return FileResponse(file_path)


@app.get("/api/projects")
def get_projects():
    """Retrieve lists of configured projects and total tracked hours per project."""
    projects_list = config.load_projects()
    stats = db.get_project_statistics()

    # Merge statistics with list
    enriched = []
    for p in projects_list:
        p_num = p["project_number"]
        enriched.append({**p, "tracked_hours": round(stats.get(p_num, 0.0), 2)})

    # Append unclassified/none stats
    if "None" in stats:
        enriched.append(
            {
                "project_number": "Unclassified",
                "description": "Activities not mapped to any specific project guidelines",
                "work_entailment": "General work, browsing, or unclassified screen states.",
                "tracked_hours": round(stats.get("None", 0.0), 2),
            }
        )

    return {"projects": enriched, "raw_stats": stats}


@app.post("/api/projects")
def save_projects(projects: List[ProjectModel]):
    """Update projects configuration list."""
    try:
        data = [p.dict() for p in projects]
        config.save_projects(data)
        return {
            "status": "success",
            "message": f"Successfully updated {len(projects)} projects.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save projects: {e}")


@app.get("/api/history")
def get_history(page: int = 1, limit: int = 30, search: Optional[str] = None):
    """Get a paginated list of historical screenshot metadata, merging pending items from raw folder and processed ones from LanceDB, alongside monthly timeline groupings."""
    try:
        import json
        import math
        from datetime import datetime

        # 1. Fetch pending raw screenshots
        pending_records = []
        try:
            queue = processor.get_pending_queue()
            for img_path, meta_path in queue:
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    pending_records.append({
                        "id": meta.get("id"),
                        "timestamp": float(meta.get("timestamp", 0.0)),
                        "image_filename": img_path.name,
                        "window_title": meta.get("window_title", "Unknown"),
                        "app_name": meta.get("app_name", "Unknown"),
                        "is_afk": bool(meta.get("is_afk", False)),
                        "description": "Pending processing...",
                        "ocr_text": None,
                        "tags": [],
                        "project_number": None,
                        "human_labeled": False,
                        "is_processed": False,
                        "unique_things": None,
                    })
                except Exception as e:
                    print(f"Error reading pending metadata {meta_path}: {e}")
        except Exception as e:
            print(f"Error reading pending queue: {e}")

        # 2. Fetch processed screenshots (fetch up to 10k to allow in-memory pagination and timeline calculation)
        db_results = []
        db_fetch_limit = 10000
        if search:
            # Embed search text for semantic search
            import requests
            url = f"{config.ollama_host}/api/embeddings"
            payload = {"model": config.embedding_model, "prompt": search, "keep_alive": 0}
            resp = requests.post(url, json=payload, timeout=5.0)
            if resp.status_code == 200:
                query_vector = resp.json().get("embedding", [])
                db_results = db.search_semantic(query_vector, limit=db_fetch_limit)
            else:
                db_results = db.get_all_records(limit=db_fetch_limit)
        else:
            db_results = db.get_all_records(limit=db_fetch_limit)

        cleaned_db = []
        for r in db_results:
            image_path_val = r.get("image_path")
            cleaned_db.append({
                "id": r.get("id"),
                "timestamp": r.get("timestamp"),
                "image_filename": (os.path.basename(image_path_val) if image_path_val else None),
                "window_title": r.get("window_title"),
                "app_name": r.get("app_name"),
                "is_afk": r.get("is_afk"),
                "description": r.get("description"),
                "ocr_text": r.get("ocr_text"),
                "tags": r.get("tags", []),
                "project_number": r.get("project_number"),
                "human_labeled": bool(r.get("human_labeled", False)),
                "is_processed": True,
                "distance": r.get("_distance"),  # Only present on semantic searches
                "unique_things": r.get("unique_things"),
            })

        # 3. Filter pending if searching (simple case-insensitive substring match)
        if search:
            search_lower = search.lower()
            filtered_pending = []
            for p in pending_records:
                if search_lower in p["window_title"].lower() or search_lower in p["app_name"].lower():
                    # For search results, we can add a nominal distance so they sort nicely
                    p["distance"] = 0.0
                    filtered_pending.append(p)
            pending_records = filtered_pending

        # 4. Merge and sort globally by timestamp descending
        processed_ids = {r.get("id") for r in cleaned_db if r.get("id")}
        pending_records = [p for p in pending_records if p.get("id") not in processed_ids]

        merged = pending_records + cleaned_db
        merged.sort(key=lambda x: x.get("timestamp", 0.0), reverse=True)

        # Deduplicate merged records by 'id' to ensure absolute uniqueness for frontend keys
        deduped_merged = []
        seen_ids = set()
        for item in merged:
            rid = item.get("id")
            if rid:
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    deduped_merged.append(item)
            else:
                deduped_merged.append(item)
        merged = deduped_merged

        total_count = len(merged)

        # 5. Calculate monthly timeline groupings based on sorted records
        seen_months = {}
        for idx, item in enumerate(merged):
            ts = item.get("timestamp", 0.0)
            try:
                dt = datetime.fromtimestamp(ts)
                month_label = dt.strftime("%B %Y")  # e.g., "June 2026"
            except Exception:
                month_label = "Unknown Date"

            if month_label not in seen_months:
                # Page calculations are 1-indexed
                target_page = (idx // limit) + 1
                seen_months[month_label] = {
                    "label": month_label,
                    "count": 0,
                    "page": target_page,
                    "timestamp": ts,
                }
            seen_months[month_label]["count"] += 1

        # Sort timeline by timestamp descending
        timeline_list = list(seen_months.values())
        timeline_list.sort(key=lambda x: x["timestamp"], reverse=True)

        # 6. Apply pagination slicing
        total_pages = math.ceil(total_count / limit) if total_count > 0 else 1

        # Clamp page within valid bounds
        current_page = page
        if current_page < 1:
            current_page = 1
        elif current_page > total_pages:
            current_page = total_pages

        offset = (current_page - 1) * limit
        paginated_items = merged[offset:offset + limit]

        return {
            "items": paginated_items,
            "total": total_count,
            "page": current_page,
            "limit": limit,
            "total_pages": total_pages,
            "timeline": timeline_list,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {e}")


@app.post("/api/process/{file_id}")
def process_single_screenshot(file_id: str):
    """Force-process a single pending screenshot synchronously."""
    try:
        import json
        raw_dir = config.screenshots_dir / "raw"
        meta_file = None
        for p in raw_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("id") == file_id:
                    meta_file = p
                    break
            except Exception:
                continue

        if not meta_file:
            raise HTTPException(status_code=404, detail="Pending screenshot not found.")

        img_file = meta_file.with_suffix(".png")
        if not img_file.exists():
            raise HTTPException(status_code=404, detail="Screenshot image file not found.")

        projects = config.load_projects()
        success = processor.process_screenshot(img_file, meta_file, projects)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to process screenshot.")

        record = db.get_record_by_id(file_id)
        if not record:
            raise HTTPException(status_code=500, detail="Processed successfully but database record not found.")

        image_path_val = record.get("image_path")
        return {
            "id": record.get("id"),
            "timestamp": record.get("timestamp"),
            "image_filename": (os.path.basename(image_path_val) if image_path_val else None),
            "window_title": record.get("window_title"),
            "app_name": record.get("app_name"),
            "is_afk": record.get("is_afk"),
            "description": record.get("description"),
            "ocr_text": record.get("ocr_text"),
            "tags": record.get("tags", []),
            "project_number": record.get("project_number"),
            "human_labeled": bool(record.get("human_labeled", False)),
            "is_processed": True,
            "logs": processor.processing_logs.get(file_id, []),
            "unique_things": record.get("unique_things"),
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error force processing: {e}")


@app.post("/api/snapshots/{record_id}/label")
def update_snapshot_label(record_id: str, payload: LabelRequest):
    """Manually assign, update, or remove a project label on any processed desktop snapshot."""
    try:
        record = db.get_record_by_id(record_id)
        if not record:
            raise HTTPException(status_code=404, detail="Snapshot record not found in database.")

        proj_num = payload.project_number
        if proj_num:
            proj_num = proj_num.strip()
            if proj_num == "" or proj_num.lower() in ("none", "unclassified"):
                proj_num = None

        db.update_project_label(record_id, proj_num, human_labeled=True)
        updated = db.get_record_by_id(record_id)

        if updated:
            image_path_val = updated.get("image_path")
            db_record = {
                "id": updated.get("id"),
                "timestamp": updated.get("timestamp"),
                "image_path": image_path_val,
                "window_title": updated.get("window_title"),
                "app_name": updated.get("app_name"),
                "is_afk": bool(updated.get("is_afk", False)),
                "description": updated.get("description"),
                "ocr_text": updated.get("ocr_text"),
                "tags": updated.get("tags", []),
                "project_number": proj_num,
                "human_labeled": True,
            }
            processor.send_to_aw_server(db_record, record_id)

        return {
            "status": "success",
            "message": f"Successfully updated project label for snapshot {record_id} to '{proj_num}' (human_labeled=True).",
            "project_number": proj_num,
            "human_labeled": True,
            "unique_things": updated.get("unique_things") if updated else None
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to update project label: {e}")


@app.get("/api/process/{file_id}/logs")
def get_processing_logs(file_id: str):
    """Retrieve the real-time processing logs for a specific screenshot, falling back to disk log files."""
    logs = processor.processing_logs.get(file_id, [])
    if not logs:
        # Check raw first
        raw_log = config.screenshots_dir / "raw" / f"{file_id}.log"
        if raw_log.exists():
            try:
                with open(raw_log, "r", encoding="utf-8") as lf:
                    logs = lf.read().splitlines()
            except Exception:
                pass

        # Then check processed
        if not logs:
            processed_log = config.screenshots_dir / "processed" / f"{file_id}.log"
            if processed_log.exists():
                try:
                    with open(processed_log, "r", encoding="utf-8") as lf:
                        logs = lf.read().splitlines()
                except Exception:
                    pass
    return {"id": file_id, "logs": logs}


@app.post("/api/process-all")
def process_all_screenshots():
    """Force-process all pending screenshots asynchronously in a background thread."""
    try:
        processor.force_process_all()
        return {
            "status": "success",
            "message": "Bulk force processing started in background.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to trigger bulk processing: {e}")


@app.post("/api/reprocess")
def reprocess_snapshots(payload: ReprocessRequest):
    """Reprocess already processed desktop snapshots with various filters."""
    import shutil
    import json
    from pathlib import Path

    try:
        # 1. Fetch matching database records
        records = []
        if payload.ids:
            for rid in payload.ids:
                rec = db.get_record_by_id(rid)
                if rec:
                    records.append(rec)
        elif payload.all:
            # Retrieve all records from LanceDB (up to a large limit)
            records = db.get_all_records(limit=100000)
        elif payload.start_time is not None and payload.end_time is not None:
            # Query by timestamp range
            where_clause = f"timestamp >= {payload.start_time} AND timestamp <= {payload.end_time}"
            records = db.query_metadata(where_clause, limit=100000)
        elif payload.limit:
            # Retrieve latest X records
            records = db.get_all_records(limit=payload.limit)
        else:
            raise HTTPException(status_code=400, detail="Must provide ids, limit, start_time/end_time, or set all=True.")

        if not records:
            return {
                "status": "success",
                "message": "No matching database records found for the given criteria.",
                "queued_count": 0,
                "skipped_count": 0
            }

        queued_count = 0
        skipped_count = 0
        skipped_purged = []
        errors = []

        processed_dir = config.screenshots_dir / "processed"
        raw_dir = config.screenshots_dir / "raw"

        # 2. Re-queue records by copying files and writing metadata JSON
        for r in records:
            rec_id = r.get("id")
            image_path_str = r.get("image_path")

            if not image_path_str or not rec_id:
                skipped_count += 1
                continue

            img_path = Path(image_path_str)
            # If path is stored as relative or absolute, normalize it
            if not img_path.is_absolute():
                img_path = processed_dir / img_path.name

            if not img_path.exists():
                skipped_count += 1
                skipped_purged.append(rec_id)
                continue

            # Ensure we are not currently processing this snapshot
            if rec_id in processor.processing_ids:
                # Already in processing queue
                skipped_count += 1
                continue

            try:
                # Copy primary processed image back to raw directory
                raw_img_path = raw_dir / img_path.name
                shutil.copy(str(img_path), str(raw_img_path))

                # Copy full context image if it exists
                full_img_filename = f"{img_path.stem}_full.png"
                full_img_path = img_path.parent / full_img_filename
                if full_img_path.exists():
                    shutil.copy(str(full_img_path), str(raw_dir / full_img_filename))

                # Build reconstructed raw metadata JSON
                metadata = {
                    "id": rec_id,
                    "timestamp": r.get("timestamp"),
                    "image_filename": img_path.name,
                    "window_title": r.get("window_title", "Unknown"),
                    "app_name": r.get("app_name", "Unknown"),
                    "is_afk": bool(r.get("is_afk", False)),
                }

                # Handle OCR bypass
                if not payload.reprocess_ocr:
                    metadata["ocr_text"] = r.get("ocr_text")
                else:
                    metadata["ocr_text"] = None

                # Write metadata file inside raw folder to trigger ingestion Phase 2 (Vision)
                meta_path = raw_dir / f"{img_path.stem}.json"
                with open(meta_path, "w", encoding="utf-8") as mf:
                    json.dump(metadata, mf, indent=2)

                queued_count += 1
            except Exception as e:
                errors.append(f"Error copying {rec_id}: {str(e)}")
                skipped_count += 1

        # 3. Trigger bulk processing in background if any items were queued
        if queued_count > 0:
            processor.force_process_all()

        message = f"Successfully queued {queued_count} snapshots for reprocessing."
        if skipped_count > 0:
            message += f" Skipped {skipped_count} items."

        return {
            "status": "success",
            "message": message,
            "queued_count": queued_count,
            "skipped_count": skipped_count,
            "skipped_purged_ids": skipped_purged,
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to initiate snapshot reprocessing: {e}")


# ---------------------------------------------------------
# Settings Endpoints
# ---------------------------------------------------------


@app.get("/api/settings")
def get_settings():
    """Retrieve all current system settings with sensitive values masked."""
    from aw_vision.settings import settings_store
    return settings_store.get_all_masked()


@app.post("/api/settings")
def update_settings(payload: SettingsUpdateRequest):
    """Save updated system settings and trigger background migrations if model or provider changes."""
    from aw_vision.settings import settings_store
    from aw_vision.db import db

    old_provider = settings_store.get("provider")
    old_ollama_emb = settings_store.get("ollama_embedding_model")
    old_gemini_emb = settings_store.get("gemini_embedding_model")

    new_settings = payload.settings
    new_provider = new_settings.get("provider", old_provider)
    new_ollama_emb = new_settings.get("ollama_embedding_model", old_ollama_emb)
    new_gemini_emb = new_settings.get("gemini_embedding_model", old_gemini_emb)

    provider_changed = (old_provider != new_provider)
    embedding_model_changed = False

    if new_provider == "gemini":
        if old_gemini_emb != new_gemini_emb:
            embedding_model_changed = True
    else:
        if old_ollama_emb != new_ollama_emb:
            embedding_model_changed = True

    # Persist setting values
    for k, v in new_settings.items():
        if k == "gemini_api_key" and v == "••••••••":
            # Retain the existing key, don't overwrite with mask
            continue
        settings_store.set(k, v)

    # Force reloading and schema update/re-embedding if needed
    settings_store.load_all()

    if provider_changed or embedding_model_changed:
        print("[Settings API] Provider or embedding model changed. Checking database schema and triggering re-embedding...")
        db._table = None  # Force database reference reload
        _ = db.table      # Accessing the table property will auto-migrate schema if dimensions changed

        # If schema migration wasn't triggered automatically, start re-embedding manually
        if not db._reembedding_status["is_running"]:
            db.trigger_batch_reembedding()

    return {"status": "success", "settings": settings_store.get_all_masked()}


@app.get("/api/settings/models")
def get_gemini_models(api_key: Optional[str] = None):
    """Retrieve available generative Gemini models, optionally verifying with a temporary key."""
    from aw_vision.gemini import query_gemini_models
    models = query_gemini_models(api_key=api_key)
    return {"models": models}


@app.post("/api/settings/test")
def test_gemini_key(payload: TestKeyRequest):
    """Test connection and validate a provided Gemini API Key against Google's servers."""
    import requests
    api_key = payload.api_key
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key is required.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        resp = requests.get(url, timeout=10.0)
        if resp.status_code == 200:
            return {"status": "success", "message": "API Key is valid. Connection successful."}
        else:
            try:
                err_msg = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text
            raise HTTPException(status_code=400, detail=f"Validation failed (HTTP {resp.status_code}): {err_msg}")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Network error connecting to Gemini API: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/settings/reembed-status")
def get_reembed_status():
    """Retrieve status of any active database-wide embedding recalculation."""
    from aw_vision.db import db
    return db._reembedding_status


# Serve compiled static React files in production/standalone mode

frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"

if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{fallback_path:path}")
    def serve_frontend(fallback_path: str):
        # Exclude API endpoints from routing fallback
        if fallback_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")

        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(), status_code=200)
        return HTMLResponse(
            content="<h1>Frontend built assets missing. Please run 'npm run build' inside frontend directory.</h1>",
            status_code=404,
        )
