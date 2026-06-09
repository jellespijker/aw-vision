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
    """Get system health and background daemon queue sizes."""
    try:
        pending_count = len(processor.get_pending_queue())
    except Exception:
        pending_count = 0

    try:
        total_records = len(db.get_all_records(limit=100000))
    except Exception:
        total_records = 0

    return {
        "watcher_running": watcher.running,
        "processor_running": processor.running,
        "pending_queue_size": pending_count,
        "processed_database_size": total_records,
        "system_load": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
        },
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
def get_history(limit: Optional[int] = 100, search: Optional[str] = None):
    """Get a list of historical screenshot metadata from LanceDB."""
    try:
        if search:
            # Embed search text
            import requests

            url = f"{config.ollama_host}/api/embeddings"
            payload = {"model": config.embedding_model, "prompt": search}
            resp = requests.post(url, json=payload, timeout=5.0)
            if resp.status_code == 200:
                query_vector = resp.json().get("embedding", [])
                results = db.search_semantic(query_vector, limit=limit)
            else:
                results = db.get_all_records(limit=limit)
        else:
            results = db.get_all_records(limit=limit)

        # Clean results for response
        cleaned = []
        for r in results:
            image_path_val = r.get("image_path")
            cleaned.append(
                {
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
                    "distance": r.get("_distance"),  # Only present on semantic searches
                }
            )
        return cleaned
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {e}")


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
