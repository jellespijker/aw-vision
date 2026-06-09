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
        resp = requests.get("http://127.0.0.1:5600/api/0/about", timeout=1.0)
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
                        "is_processed": False,
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
            payload = {"model": config.embedding_model, "prompt": search}
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
                "is_processed": True,
                "distance": r.get("_distance"),  # Only present on semantic searches
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
        merged = pending_records + cleaned_db
        merged.sort(key=lambda x: x.get("timestamp", 0.0), reverse=True)

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
            "is_processed": True,
            "logs": processor.processing_logs.get(file_id, []),
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error force processing: {e}")


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
