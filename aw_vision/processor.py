import json
import os
import shutil
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import ollama
import psutil
import requests

from aw_vision.config import config
from aw_vision.db import db


class BulkProcessor:
    def __init__(self):
        self.raw_dir = config.screenshots_dir / "raw"
        self.processed_dir = config.screenshots_dir / "processed"
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.processing_ids = set()
        self.processing_logs = {}

        # Ensure directories exist
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def log_step(self, rec_id: str, message: str):
        """Append a timestamped progress message for a specific file_id."""
        timestamp_str = datetime.now().strftime("%H:%M:%S")
        msg = f"[{timestamp_str}] {message}"
        print(f"[{rec_id}] {msg}")
        with self.lock:
            if rec_id not in self.processing_logs:
                self.processing_logs[rec_id] = []
            self.processing_logs[rec_id].append(msg)
            # Keep logs bounded to last 100 screenshots to prevent memory leak
            if len(self.processing_logs) > 100:
                oldest_key = next(iter(self.processing_logs))
                self.processing_logs.pop(oldest_key, None)

    def get_nvidia_gpus_usage(self) -> list[dict]:
        """Query nvidia-smi to get GPU utilization and process list."""
        import shutil
        import subprocess

        if not shutil.which("nvidia-smi"):
            return []

        try:
            # Query GPU index and utilization
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,utilization.gpu", "--format=csv,noheader,nounits"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1.5
            )
            if res.returncode != 0:
                return []

            gpus = []
            for line in res.stdout.strip().split("\n"):
                if line:
                    parts = line.split(",")
                    if len(parts) == 2:
                        idx = int(parts[0].strip())
                        util = float(parts[1].strip())
                        gpus.append({"index": idx, "utilization": util, "ollama_running": False})

            # Check if any ollama processes are running on the GPU
            res_proc = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=gpu_index,pid,process_name", "--format=csv,noheader"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1.5
            )
            if res_proc.returncode == 0:
                for line in res_proc.stdout.strip().split("\n"):
                    if line:
                        parts = line.split(",")
                        if len(parts) >= 3:
                            gpu_idx_str = parts[0].strip()
                            proc_name = parts[2].strip().lower()
                            if "ollama" in proc_name or "llama-server" in proc_name or "llama" in proc_name:
                                try:
                                    gpu_idx = int(gpu_idx_str)
                                    for gpu in gpus:
                                        if gpu["index"] == gpu_idx:
                                            gpu["ollama_running"] = True
                                except ValueError:
                                    pass

            return gpus
        except Exception as e:
            print(f"Error querying nvidia-smi for GPU utilization: {e}")
            return []

    def is_system_idle(self) -> bool:
        """Check if CPU, Memory, and optionally GPU usage are below idle thresholds."""
        cpu_usage = psutil.cpu_percent(interval=0.5)
        mem_usage = psutil.virtual_memory().percent

        idle = cpu_usage < config.cpu_threshold and mem_usage < config.memory_threshold
        status_msg = f"[{datetime.now()}] System resources check - CPU: {cpu_usage}% (limit {config.cpu_threshold}%), Memory: {mem_usage}% (limit {config.memory_threshold}%)"

        # Check GPU usage if nvidia-smi is available
        gpus = self.get_nvidia_gpus_usage()
        gpu_active_limit_exceeded = False

        for gpu in gpus:
            idx = gpu["index"]
            util = gpu["utilization"]
            ollama_active = gpu["ollama_running"]
            status_msg += f", GPU[{idx}]: {util}%"
            if ollama_active:
                status_msg += " (Ollama running on GPU)"
                if util > config.gpu_threshold:
                    gpu_active_limit_exceeded = True
                    status_msg += f" [BUSY: >{config.gpu_threshold}%]"

        print(status_msg)
        if gpu_active_limit_exceeded:
            return False

        return idle

    def get_pending_queue(self) -> list[tuple[Path, Path]]:
        """Return lists of pending (screenshot_path, metadata_path) tuples."""
        queue = []
        for file in self.raw_dir.glob("*.json"):
            img_file = file.with_suffix(".png")
            if img_file.exists():
                queue.append((img_file, file))
        # Sort by timestamp (oldest first)
        queue.sort(key=lambda x: x[1].name)
        return queue

    def get_ollama_embedding(self, text: str, rec_id: str = None) -> list[float]:
        """Fetch vector embedding for the description using Ollama."""
        try:
            url = f"{config.ollama_host}/api/embeddings"
            payload = {"model": config.embedding_model, "prompt": text, "keep_alive": 0}
            resp = requests.post(url, json=payload, timeout=30.0)
            if resp.status_code == 200:
                return resp.json().get("embedding", [])
        except Exception as e:
            err_msg = f"Error generating embedding from Ollama: {e}"
            if rec_id:
                self.log_step(rec_id, err_msg)
            else:
                print(err_msg)

        # Fallback to zero vector if embedding fails (to prevent pipeline crash)
        dim = db.get_embedding_dimension()
        return [0.0] * dim

    def extract_ocr_text(self, img_path: Path, rec_id: str = None, keep_alive: int = 0) -> str:
        """Call local Ollama OCR model to extract all readable text from screenshot."""
        try:
            msg = f"Running OCR on screenshot using model: {config.ocr_model}"
            if rec_id:
                self.log_step(rec_id, msg)
            else:
                print(f"[{datetime.now()}] {msg}")
            client = ollama.Client(host=config.ollama_host)
            prompt = "Extract all readable text, titles, labels, or content from this desktop screenshot exactly as shown. Do not explain, describe, or add any meta-commentary. Just output the extracted text."
            response = client.chat(
                model=config.ocr_model,
                messages=[{"role": "user", "content": prompt, "images": [str(img_path)]}],
                options={"temperature": 0.1},
                keep_alive=keep_alive,
            )
            ocr_text = response.get("message", {}).get("content", "").strip()
            msg2 = f"OCR Extracted text length: {len(ocr_text)}"
            if rec_id:
                self.log_step(rec_id, msg2)
            else:
                print(f"[{datetime.now()}] {msg2}")
            return ocr_text
        except Exception as e:
            err_msg = f"Error running OCR with Ollama model {config.ocr_model}: {e}"
            if rec_id:
                self.log_step(rec_id, err_msg)
            else:
                print(err_msg)
            return ""

    def optimize_image(self, img_path: Path, rec_id: str, max_size: int = 1200):
        """Resize image to a maximum dimension of max_size maintaining aspect ratio, saving disk space and speeding up vision/OCR models."""
        if not img_path.exists():
            return
        try:
            from PIL import Image
            with Image.open(img_path) as img:
                width, height = img.size
                if max(width, height) <= max_size:
                    return

                self.log_step(rec_id, f"Optimizing screenshot dimensions (original: {width}x{height}) to max {max_size}px...")
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                img.save(img_path, "PNG", optimize=True)
                new_width, new_height = img.size
                self.log_step(rec_id, f"Screenshot successfully optimized to {new_width}x{new_height}.")
        except Exception as e:
            self.log_step(rec_id, f"Warning: Could not optimize screenshot {img_path.name}: {e}")

    def send_to_aw_server(self, record: dict, rec_id: str):
        """Send the processed screenshot metadata as an event to aw-server."""
        import socket
        try:
            hostname = socket.gethostname()
            bucket_id = f"aw-vision-processed_{hostname}"

            # Ensure bucket exists (aw-server handles 304 or 200)
            url_create = f"http://localhost:5600/api/0/buckets/{bucket_id}"
            create_payload = {
                "client": "aw-vision",
                "type": "vision-processed",
                "hostname": hostname
            }
            try:
                requests.post(url_create, json=create_payload, timeout=2.0)
            except Exception as e:
                self.log_step(rec_id, f"Warning: Could not create/verify aw-server bucket: {e}")
                return

            # Convert timestamp to ISO 8601 string in UTC
            from datetime import datetime, timezone
            ts = record.get("timestamp", time.time())
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            now_iso = dt.isoformat()

            # Formulate event payload
            event = {
                "timestamp": now_iso,
                "duration": float(config.screenshot_interval),
                "data": {
                    "id": record["id"],
                    "app": record["app_name"],
                    "title": record["window_title"],
                    "description": record["description"],
                    "tags": record["tags"],
                    "project_number": record["project_number"] or "None"
                }
            }

            url_events = f"http://localhost:5600/api/0/buckets/{bucket_id}/events"
            resp = requests.post(url_events, json=[event], timeout=2.0)
            if resp.status_code == 200:
                self.log_step(rec_id, "Successfully mirrored processed event to aw-server bucket.")
            else:
                self.log_step(rec_id, f"Warning: Failed to mirror event to aw-server (Status {resp.status_code}): {resp.text}")
        except Exception as e:
            self.log_step(rec_id, f"Warning: Error sending event to aw-server: {e}")

    def run_retention_cleanup(self):
        """Scan database for expired records, delete their screenshot files, and set image_path to None."""
        try:
            print(f"[{datetime.now()}] Running screenshot retention cleanup check...")
            records = db.get_all_records(limit=10000)
            now_timestamp = time.time()
            max_age_seconds = config.max_screenshot_lifetime_days * 86400
            purged_count = 0

            for r in records:
                rec_id = r.get("id")
                timestamp = r.get("timestamp", 0)
                image_path_str = r.get("image_path")

                if not image_path_str or not rec_id:
                    continue

                if now_timestamp - timestamp > max_age_seconds:
                    p = Path(image_path_str)
                    if p.exists():
                        try:
                            p.unlink()
                            print(f"Deleted expired screenshot file: {p}")
                        except Exception as e:
                            print(f"Error deleting file {p}: {e}")

                    # Also delete corresponding full screenshot if present (for retention)
                    full_p = p.parent / f"{p.stem}_full.png"
                    if full_p.exists():
                        try:
                            full_p.unlink()
                            print(f"Deleted expired full screenshot file: {full_p}")
                        except Exception as e:
                            print(f"Error deleting full file {full_p}: {e}")

                    # Also delete corresponding log file if present (for retention)
                    log_p = p.parent / f"{p.stem}.log"
                    if log_p.exists():
                        try:
                            log_p.unlink()
                            print(f"Deleted expired log file: {log_p}")
                        except Exception as e:
                            print(f"Error deleting log file {log_p}: {e}")

                    # Also check raw directory for same filename if not cleared
                    raw_p = self.raw_dir / p.name
                    if raw_p.exists():
                        try:
                            raw_p.unlink()
                            print(f"Deleted expired raw file: {raw_p}")
                        except Exception as e:
                            print(f"Error deleting raw file {raw_p}: {e}")

                    raw_full_p = self.raw_dir / f"{p.stem}_full.png"
                    if raw_full_p.exists():
                        try:
                            raw_full_p.unlink()
                            print(f"Deleted expired raw full file: {raw_full_p}")
                        except Exception as e:
                            print(f"Error deleting raw full file {raw_full_p}: {e}")

                    raw_log_p = self.raw_dir / f"{p.stem}.log"
                    if raw_log_p.exists():
                        try:
                            raw_log_p.unlink()
                            print(f"Deleted expired raw log file: {raw_log_p}")
                        except Exception as e:
                            print(f"Error deleting raw log file {raw_log_p}: {e}")

                    db.nullify_expired_screenshot_path(rec_id)
                    purged_count += 1

            if purged_count > 0:
                print(
                    f"[{datetime.now()}] Screenshot retention cleanup finished. Purged {purged_count} expired screenshots."
                )
            else:
                print(f"[{datetime.now()}] Screenshot retention cleanup finished. No expired files found.")
        except Exception as e:
            print(f"Error running retention cleanup: {e}")
            traceback.print_exc()

    def process_batch(self, queue: list[tuple[Path, Path]], projects: list) -> bool:
        """Process a list of raw screenshot and metadata tuples sequentially in distinct stages to limit Ollama model load/unload cycles."""
        batch_items = []
        with self.lock:
            for img_path, meta_path in queue:
                if not meta_path.exists() or not img_path.exists():
                    continue
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    rec_id = meta["id"]
                    if rec_id in self.processing_ids:
                        print(f"Screenshot {rec_id} is already being processed. Skipping.")
                        continue
                    self.processing_ids.add(rec_id)
                    batch_items.append((img_path, meta_path, rec_id, meta))
                except Exception as e:
                    print(f"Error reading metadata during batch filter for {meta_path}: {e}")
                    continue

        if not batch_items:
            return False

        N = len(batch_items)
        print(f"[{datetime.now()}] Batch-processing {N} screenshots in staged sweeps...")

        # -------------------------------------------------------------
        # Phase 1: Optimize & OCR Sweep
        # -------------------------------------------------------------
        for idx, (img_path, meta_path, rec_id, meta) in enumerate(batch_items):
            try:
                self.log_step(rec_id, f"Phase 1/3: Image Optimization & OCR extraction (item {idx + 1}/{N} in batch)")

                # Image optimization
                full_img_filename = f"{img_path.stem}_full.png"
                full_img_path = img_path.parent / full_img_filename

                self.optimize_image(img_path, rec_id, max_size=1200)
                if full_img_path.exists():
                    self.optimize_image(full_img_path, rec_id, max_size=1200)

                # Only run OCR if not already cached
                if "ocr_text" not in meta or meta["ocr_text"] is None:
                    # Keep model loaded during the sweep, unload immediately on the last item of Phase 1
                    keep_alive = 0 if (idx == N - 1) else 300
                    ocr_text = self.extract_ocr_text(img_path, rec_id, keep_alive=keep_alive)
                    meta["ocr_text"] = ocr_text

                    # Persist ocr_text to the metadata JSON file on disk
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=2)
                else:
                    self.log_step(rec_id, "OCR text already cached in metadata JSON. Skipping OCR.")
            except Exception as e:
                self.log_step(rec_id, f"Error in Phase 1 (OCR) for {img_path.name}: {e}")

        # -------------------------------------------------------------
        # Phase 2: Vision Analysis Sweep
        # -------------------------------------------------------------
        for idx, (img_path, meta_path, rec_id, meta) in enumerate(batch_items):
            try:
                self.log_step(rec_id, f"Phase 2/3: Vision model analysis & Project classification (item {idx + 1}/{N} in batch)")

                # Only run Vision if not already processed (meaning we don't have description)
                if "description" not in meta or meta["description"] is None:
                    full_img_filename = f"{img_path.stem}_full.png"
                    full_img_path = img_path.parent / full_img_filename

                    images_payload = []
                    if full_img_path.exists():
                        # Pass focused crop as image 1, and fullscreen desktop as image 2 (context)
                        images_payload = [str(img_path), str(full_img_path)]
                    else:
                        images_payload = [str(img_path)]

                    aw_context_str = "None"
                    bucket_context = meta.get("aw_bucket_context", {})
                    if bucket_context:
                        aw_context_str = json.dumps(bucket_context, indent=2, ensure_ascii=False)

                    existing_tags = db.get_all_unique_tags()
                    if len(existing_tags) > 100:
                        existing_tags = existing_tags[:100]

                    projects_str = json.dumps(projects, indent=2, ensure_ascii=False)
                    has_dual_images = full_img_path.exists()

                    # Fetch temporal neighbor context and app statistics
                    timestamp = float(meta.get("timestamp", time.time()))
                    past_neighbor = db.get_past_neighbor(timestamp)
                    future_neighbor = db.get_future_neighbor(timestamp)

                    neighbor_context_str = ""
                    if past_neighbor:
                        p_proj = past_neighbor.get("project_number") or "None"
                        p_human = "Yes (Verified)" if past_neighbor.get("human_labeled") else "No (Auto-classified)"
                        neighbor_context_str += f"""- PRECEDING SNAPSHOT (Past Neighbor):
  * Application: {past_neighbor.get('app_name', 'Unknown')}
  * Window Title: {past_neighbor.get('window_title', 'Unknown')}
  * Description: {past_neighbor.get('description', 'No description')}
  * Project Assigned: {p_proj}
  * Label Is Verified by Human: {p_human}
"""
                    if future_neighbor:
                        f_proj = future_neighbor.get("project_number") or "None"
                        f_human = "Yes (Verified)" if future_neighbor.get("human_labeled") else "No (Auto-classified)"
                        neighbor_context_str += f"""- SUCCEEDING SNAPSHOT (Future Neighbor):
  * Application: {future_neighbor.get('app_name', 'Unknown')}
  * Window Title: {future_neighbor.get('window_title', 'Unknown')}
  * Description: {future_neighbor.get('description', 'No description')}
  * Project Assigned: {f_proj}
  * Label Is Verified by Human: {f_human}
"""
                    if not neighbor_context_str:
                        neighbor_context_str = "- No chronological neighbor snapshots are currently available."

                    app_name = meta.get("app_name", "Unknown")
                    app_freqs = db.get_app_project_frequencies(app_name)
                    app_freq_str = ""
                    if app_freqs:
                        app_freq_str = "\n".join([f"  * Project {proj}: score {freq:.1f}" for proj, freq in app_freqs.items()])
                    else:
                        app_freq_str = f"  * No historical project associations for '{app_name}'."

                    prompt_text = f"""
### USER METADATA CONTEXT
- Active Application: {app_name}
- Active Window Title: {meta.get('window_title', 'Unknown')}
- Extracted Focused Screen Text (OCR):
---
{meta.get('ocr_text', '')}
---

### ADDITIONAL ACTIVITYWATCH BUCKET STATES
These represent other active watcher logs from the user's computer around this timestamp (e.g., active editor files, active browser URLs):
---
{aw_context_str}
---

### PROJECT REFERENCE CATALOG
Below is the list of active work projects you can match against:
{projects_str}

### CHRONOLOGICAL NEIGHBORS & TEMPORAL CONTEXT
Below are details of the immediately adjacent snapshot recordings (past and future). Use this to maintain temporal coherence across computer activity. If adjacent snapshots are assigned to a certain project (especially if human-verified), prefer to stay on that project context unless there's a clear change in activity.
---
{neighbor_context_str}
---

### APPLICATION PROJECT HISTORICAL STATISTICS
Historically, the application '{app_name}' has been mapped to these projects with the following weighted frequencies (higher scores indicate stronger/human-verified correlation):
---
{app_freq_str}
---

### SCREENSHOT STRUCTURE & PRIORITIES
"""
                    if has_dual_images:
                        prompt_text += """
You are provided with two screenshots of the user's desktop taken at the exact same moment:
1. **First Image**: A focused, cropped screenshot of the **Active Window** only.
2. **Second Image**: A **Fullscreen Desktop** screenshot containing the entire display area (sidebar, background apps, adjacent windows, etc.).

**CRITICAL CRITERIA**:
- Your primary subject of analysis is the **Active Window** (First Image).
- The OCR text provided above belongs exclusively to this Active Window (First Image).
- The Fullscreen Desktop (Second Image) is provided purely as additional context. Any elements in the Fullscreen Desktop (Second Image) that are outside of the Active Window are supplementary or tangent, and may be completely unrelated to the primary task. You must prioritize the Active Window's contents and the OCR text when describing and classifying the work.
"""
                    else:
                        prompt_text += """
You are provided with a single screenshot of the user's desktop.
- Analyze the screenshot, the active application metadata, and the OCR text to describe and classify the work.
"""

                    prompt_text += f"""
### SYSTEM INSTRUCTIONS & CLASSIFICATION RULES
You are a highly precise automated time-tracking and productivity classification assistant. Your task is to analyze the user's desktop state and categorize their work.

Follow these strict rules:
1. **Description Generation**:
   - Provide a highly detailed, objective, and granular description of the active window and task.
   - Specify exactly what is being viewed or worked on (e.g., specific file names, code functions, browser URLs, searched keywords, active spreadsheet columns, or chat messages).
   - If the user is on a website like LinkedIn, GitHub, or Youtube, specify the exact profile, issue, repository, channel, or video being viewed.
   - Synthesize the OCR text, Active Window/Fullscreen screenshot details, and the Additional ActivityWatch Bucket States (such as the currently open code file or browser URL) to form a cohesive, accurate description of the user's current task.
   - Do NOT talk about the user's background or general projects unless there is direct evidence of it being the active task on the screen.
   - Ignore irrelevant sidebar elements like Chrome bookmarks, adjacent browser tabs, or inactive chat lists unless they are the direct subject.

2. **Project Matching**:
   - Compare the active window content, OCR text, and ActivityWatch bucket states against the PROJECT REFERENCE CATALOG above.
   - **CRITICAL**: Be extremely conservative and precise when matching projects. If there is no strong, explicit, and direct evidence correlating the active screen contents to a project's description/entailment, you MUST output "None".
   - Do NOT match a project just because the word or name appears in an inactive sidebar chat title, adjacent tab name, or browser bookmark.
   - Do NOT assume that external company profiles (like LinkedIn company pages or news articles) are related to the user's active development projects. For example, viewing a generic LinkedIn page should map to "None" or a general management/business category, never a specific local research or R&D project (like NGP Research) unless they are directly editing that project's architecture.

3. **Tag Generation**:
- Return 3 to 7 highly relevant, technical tags or keywords representing the current task (e.g., ["react", "api-integration", "customer-outreach", "documentation", "system-diagnostic"]).
- Re-use tags from this list of existing tags whenever possible to keep the database consistent: {existing_tags}
4. **Temporal Coherence**:
   - Utilize the CHRONOLOGICAL NEIGHBORS and APPLICATION PROJECT HISTORICAL STATISTICS to guide your categorization.
   - If the preceding or succeeding snapshots are assigned to a project and the current screenshot shows continuous activity in the same context, you should assign the same project to ensure temporal continuity.
   - If a human-verified project assignment exists in the neighboring context for the same application, give it strong preference.

You MUST respond in valid JSON format matching the schema below. Do not include any markdown wrapper outside of the JSON output.
JSON Schema:
{{
  "description": "string",
  "tags": ["string"],
  "project_number": "string"
}}
"""

                    self.log_step(rec_id, f"Using images for vision analysis: {[os.path.basename(img) for img in images_payload]}")
                    self.log_step(rec_id, f"Calling vision model '{config.vision_model}'...")

                    # Keep model loaded during sweep, unload on the very last item of Phase 2
                    keep_alive = 0 if (idx == N - 1) else 300

                    client = ollama.Client(host=config.ollama_host)
                    response = client.chat(
                        model=config.vision_model,
                        messages=[{"role": "user", "content": prompt_text, "images": images_payload}],
                        format="json",
                        options={"temperature": 0.2},
                        keep_alive=keep_alive,
                    )

                    raw_response = response.get("message", {}).get("content", "")
                    self.log_step(rec_id, f"Ollama Vision response received (length {len(raw_response)}).")

                    parsed = json.loads(raw_response)
                    meta["description"] = parsed.get("description", "No description generated.")
                    meta["tags"] = parsed.get("tags", [])
                    meta["project_number"] = parsed.get("project_number", "None")

                    # Persist results to metadata JSON file on disk
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=2)
                else:
                    self.log_step(rec_id, "Vision analysis results already cached in metadata. Skipping vision model.")
            except Exception as e:
                self.log_step(rec_id, f"Error in Phase 2 (Vision) for {img_path.name}: {e}")

        # -------------------------------------------------------------
        # Phase 3: Embeddings & DB Commit Sweep
        # -------------------------------------------------------------
        success_count = 0
        for idx, (img_path, meta_path, rec_id, meta) in enumerate(batch_items):
            try:
                self.log_step(rec_id, f"Phase 3/3: Embedding calculation, DB commit & Cleanup (item {idx + 1}/{N} in batch)")

                description = meta.get("description", "No description generated.")
                ocr_text = meta.get("ocr_text", "")
                tags = meta.get("tags", [])
                project_number = meta.get("project_number", "None")
                if project_number == "None":
                    project_number = None

                self.log_step(rec_id, f"Generating semantic embedding (1024-dim joint vector) using '{config.embedding_model}'...")
                embedding_text = f"Description: {description}\n\nExtracted Screen Text:\n{ocr_text}"

                # Keep embedding model loaded during the sweep, unload on the very last item of Phase 3
                keep_alive = 0 if (idx == N - 1) else 300

                embedding = []
                try:
                    url = f"{config.ollama_host}/api/embeddings"
                    payload = {"model": config.embedding_model, "prompt": embedding_text, "keep_alive": keep_alive}
                    resp = requests.post(url, json=payload, timeout=30.0)
                    if resp.status_code == 200:
                        embedding = resp.json().get("embedding", [])
                except Exception as ee:
                    self.log_step(rec_id, f"Error generating embedding from Ollama: {ee}")

                if not embedding:
                    dim = db.get_embedding_dimension()
                    embedding = [0.0] * dim

                # Build database record
                db_record = {
                    "id": meta["id"],
                    "timestamp": float(meta["timestamp"]),
                    "image_path": str(self.processed_dir / img_path.name),
                    "window_title": meta.get("window_title", "Unknown"),
                    "app_name": meta.get("app_name", "Unknown"),
                    "is_afk": bool(meta.get("is_afk", False)),
                    "description": description,
                    "ocr_text": ocr_text,
                    "tags": tags,
                    "project_number": project_number,
                    "human_labeled": False,
                    "vector": embedding,
                }

                # Commit to database
                self.log_step(rec_id, "Committing record to local LanceDB database...")
                db.insert_screenshot(db_record)

                # Mirror metadata to aw-server processed bucket
                self.send_to_aw_server(db_record, rec_id)

                # Move image & metadata to processed directory
                self.log_step(rec_id, "Archiving screenshots and clearing temporary ingestion files...")
                shutil.move(str(img_path), str(self.processed_dir / img_path.name))

                full_img_filename = f"{img_path.stem}_full.png"
                full_img_path = img_path.parent / full_img_filename
                if full_img_path.exists():
                    shutil.move(str(full_img_path), str(self.processed_dir / full_img_filename))

                # Delete temporary raw metadata JSON file
                if meta_path.exists():
                    meta_path.unlink()

                self.log_step(rec_id, "Processing completed successfully.")

                # Save processed log file to disk
                try:
                    log_file = self.processed_dir / f"{rec_id}.log"
                    with open(log_file, "w", encoding="utf-8") as lf:
                        lf.write("\n".join(self.processing_logs.get(rec_id, [])))
                except Exception as le:
                    print(f"Error saving processed log file: {le}")

                success_count += 1
            except Exception as e:
                err_msg = f"Error in Phase 3 (Embedding/Commit) for {img_path.name}: {e}"
                self.log_step(rec_id, err_msg)
                try:
                    log_file = img_path.parent / f"{rec_id}.log"
                    with open(log_file, "w", encoding="utf-8") as lf:
                        lf.write("\n".join(self.processing_logs.get(rec_id, [])))
                except Exception as le:
                    print(f"Error saving raw log file: {le}")
                traceback.print_exc()

        # Clean up processing_ids
        with self.lock:
            for _, _, rec_id, _ in batch_items:
                self.processing_ids.discard(rec_id)

        return success_count > 0

    def process_screenshot(self, img_path: Path, meta_path: Path, projects: list) -> bool:
        """Process a single screenshot by wrapping it as a batch of 1 and calling process_batch."""
        return self.process_batch([(img_path, meta_path)], projects)

    def force_process_all(self):
        """Force process all pending items immediately in an optimized background batch thread."""
        def run_force():
            print(f"[{datetime.now()}] Force processing all starting...")
            try:
                queue = self.get_pending_queue()
                if not queue:
                    print(f"[{datetime.now()}] Force processing all: no pending items.")
                    return
                projects = config.load_projects()
                self.process_batch(queue, projects)
            except Exception as e:
                print(f"Error in force_process_all thread: {e}")
            finally:
                print(f"[{datetime.now()}] Force processing all finished.")

        threading.Thread(target=run_force, daemon=True).start()

    def _loop(self):
        print(f"Processor daemon started. Running check every {config.check_interval}s.")
        last_cleanup_time = 0.0
        while self.running:
            try:
                # Run storage retention cleanup periodically
                now = time.time()
                cleanup_interval_seconds = config.cleanup_interval_hours * 3600
                if now - last_cleanup_time >= cleanup_interval_seconds:
                    self.run_retention_cleanup()
                    last_cleanup_time = now

                queue = self.get_pending_queue()
                if queue:
                    print(f"Pending screenshots in queue: {len(queue)}")
                    # Check if system is idle before running heavy Ollama jobs
                    if self.is_system_idle():
                        projects = config.load_projects()
                        # Process the entire queue as an optimized batch!
                        self.process_batch(queue, projects)
                    else:
                        print("System is busy (not idle). Postponing screenshot processing.")
                else:
                    # No pending files, we're fully caught up
                    pass
            except Exception as e:
                print(f"Error in processor loop: {e}")

            # Sleep until next check
            for _ in range(config.check_interval * 10):
                if not self.running:
                    break
                time.sleep(0.1)

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
        print("Processor daemon stopped.")


# Instantiate processor
processor = BulkProcessor()
