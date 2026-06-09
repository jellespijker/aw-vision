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

    def extract_ocr_text(self, img_path: Path, rec_id: str = None) -> str:
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
                keep_alive=0,
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

    def process_screenshot(self, img_path: Path, meta_path: Path, projects: list) -> bool:
        """Process a single screenshot using Ollama vision model and commit to database."""
        if not meta_path.exists() or not img_path.exists():
            return False

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            rec_id = metadata["id"]
        except Exception as e:
            print(f"Error reading metadata file {meta_path}: {e}")
            return False

        with self.lock:
            if rec_id in self.processing_ids:
                print(f"Screenshot {rec_id} is already being processed. Skipping.")
                return False
            self.processing_ids.add(rec_id)

        try:
            app_name = metadata.get("app_name", "Unknown")
            window_title = metadata.get("window_title", "Unknown")

            self.log_step(rec_id, f"Initializing processing for screenshot: {img_path.name}")
            self.log_step(rec_id, f"App: {app_name}, Window: {window_title[:40]}")

            # Optimize screenshots before running OCR/Vision to save disk, memory, and improve model performance
            full_img_filename = f"{img_path.stem}_full.png"
            full_img_path = img_path.parent / full_img_filename

            self.optimize_image(img_path, rec_id, max_size=1200)
            if full_img_path.exists():
                self.optimize_image(full_img_path, rec_id, max_size=1200)

            # 1. Run OCR extraction
            ocr_text = self.extract_ocr_text(img_path, rec_id)

            # 2. Get unique tags for tag reuse
            self.log_step(rec_id, "Retrieving existing database tags for classification...")
            existing_tags = db.get_all_unique_tags()
            if len(existing_tags) > 100:
                existing_tags = existing_tags[:100]  # Cap for prompt efficiency

            projects_str = json.dumps(projects, indent=2, ensure_ascii=False)

            # Prompt for Ollama vision model
            prompt_text = f"""
### USER METADATA CONTEXT
- Active Application: {app_name}
- Active Window Title: {window_title}
- Extracted Screen Text (OCR):
---
{ocr_text}
---

### PROJECT REFERENCE CATALOG
Below is the list of active work projects you can match against:
{projects_str}

### SYSTEM INSTRUCTIONS & CLASSIFICATION RULES
You are a highly precise automated time-tracking and productivity classification assistant. Your task is to analyze the user's desktop screenshot alongside the provided metadata context and categorize their work.

Follow these strict rules:
1. **Description Generation**:
   - Provide a highly detailed, objective, and granular description of the active window and task.
   - Specify exactly what is being viewed or worked on (e.g., specific file names, code functions, browser URLs, searched keywords, active spreadsheet columns, or chat messages).
   - If the user is on a website like LinkedIn, GitHub, or Youtube, specify the exact profile, issue, repository, channel, or video being viewed.
   - Do NOT talk about the user's background or general projects unless there is direct evidence of it being the active task on the screen.
   - Ignore irrelevant sidebar elements like Chrome bookmarks, adjacent browser tabs, or inactive chat lists unless they are the direct subject.

2. **Project Matching**:
   - Compare the active window content and OCR text against the PROJECT REFERENCE CATALOG above.
   - **CRITICAL**: Be extremely conservative and precise when matching projects. If there is no strong, explicit, and direct evidence correlating the active screen contents to a project's description/entailment, you MUST output "None".
   - Do NOT match a project just because the word or name appears in an inactive sidebar chat title, adjacent tab name, or browser bookmark.
   - Do NOT assume that external company profiles (like LinkedIn company pages or news articles) are related to the user's active development projects. For example, viewing a generic LinkedIn page should map to "None" or a general management/business category, never a specific local research or R&D project (like NGP Research) unless they are directly editing that project's architecture.

3. **Tag Generation**:
   - Return 3 to 7 highly relevant, technical tags or keywords representing the current task (e.g., ["react", "api-integration", "customer-outreach", "documentation", "system-diagnostic"]).
   - Re-use tags from this list of existing tags whenever possible to keep the database consistent: {existing_tags}
   - Only generate a new tag if none of the existing ones fit the specific technical domain.

You MUST respond in valid JSON format matching the schema below. Do not include any markdown wrapper outside of the JSON output.
JSON Schema:
{{
  "description": "string",
  "tags": ["string"],
  "project_number": "string"
}}
"""

            # Determine which image to send to the vision model for full context analysis
            full_img_filename = f"{img_path.stem}_full.png"
            full_img_path = img_path.parent / full_img_filename
            vision_img_path = full_img_path if full_img_path.exists() else img_path

            self.log_step(rec_id, f"Using image for vision analysis: {vision_img_path.name}")
            self.log_step(rec_id, f"Calling vision model '{config.vision_model}' for task description, tagging, and project matching...")

            # Call Ollama chat vision endpoint
            client = ollama.Client(host=config.ollama_host)
            response = client.chat(
                model=config.vision_model,
                messages=[{"role": "user", "content": prompt_text, "images": [str(vision_img_path)]}],
                format="json",
                options={"temperature": 0.2},
                keep_alive=0,
            )

            # Parse JSON response
            raw_response = response.get("message", {}).get("content", "")
            self.log_step(rec_id, f"Ollama Vision response received (length {len(raw_response)}).")

            parsed = json.loads(raw_response)
            description = parsed.get("description", "No description generated.")
            tags = parsed.get("tags", [])
            project_number = parsed.get("project_number", "None")
            if project_number == "None":
                project_number = None

            self.log_step(rec_id, f"Classification result - Project: {project_number or 'None'}, Tags: {tags}")

            # 3. Get embedding of the combined description & OCR text
            self.log_step(rec_id, f"Generating semantic embedding (1024-dim joint vector) using '{config.embedding_model}'...")
            embedding_text = f"Description: {description}\n\nExtracted Screen Text:\n{ocr_text}"
            embedding = self.get_ollama_embedding(embedding_text, rec_id)

            # Build database record
            db_record = {
                "id": metadata["id"],
                "timestamp": float(metadata["timestamp"]),
                "image_path": str(self.processed_dir / img_path.name),
                "window_title": window_title,
                "app_name": app_name,
                "is_afk": bool(metadata.get("is_afk", False)),
                "description": description,
                "ocr_text": ocr_text,
                "tags": tags,
                "project_number": project_number,
                "vector": embedding,
            }

            # Insert into database
            self.log_step(rec_id, "Committing record to local LanceDB database...")
            db.insert_screenshot(db_record)

            # Mirror metadata to aw-server processed bucket
            self.send_to_aw_server(db_record, rec_id)

            # Move image & metadata to processed directory
            self.log_step(rec_id, "Archiving screenshots and clearing temporary ingestion files...")
            shutil.move(str(img_path), str(self.processed_dir / img_path.name))
            if full_img_path.exists():
                shutil.move(str(full_img_path), str(self.processed_dir / full_img_filename))
            meta_path.unlink()  # Delete temporary raw metadata JSON file

            self.log_step(rec_id, "Processing completed successfully.")

            # Save processed log file to disk
            try:
                log_file = self.processed_dir / f"{rec_id}.log"
                with open(log_file, "w", encoding="utf-8") as lf:
                    lf.write("\n".join(self.processing_logs.get(rec_id, [])))
            except Exception as le:
                print(f"Error saving processed log file: {le}")

            return True

        except Exception as e:
            err_msg = f"Error processing screenshot {img_path.name}: {e}"
            self.log_step(rec_id, err_msg)
            # Save failed log file to disk in raw directory
            try:
                log_file = img_path.parent / f"{rec_id}.log"
                with open(log_file, "w", encoding="utf-8") as lf:
                    lf.write("\n".join(self.processing_logs.get(rec_id, [])))
            except Exception as le:
                print(f"Error saving raw log file: {le}")
            traceback.print_exc()
            return False
        finally:
            with self.lock:
                self.processing_ids.discard(rec_id)

    def force_process_all(self):
        """Force process all pending items immediately in a background thread."""
        def run_force():
            print(f"[{datetime.now()}] Force processing all starting...")
            try:
                queue = self.get_pending_queue()
                if not queue:
                    print(f"[{datetime.now()}] Force processing all: no pending items.")
                    return
                projects = config.load_projects()
                for img_path, meta_path in queue:
                    self.process_screenshot(img_path, meta_path, projects)
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
                        # Process only one screenshot per check to avoid sudden CPU spikes
                        img_path, meta_path = queue[0]
                        self.process_screenshot(img_path, meta_path, projects)
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
