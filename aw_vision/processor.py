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

        # Ensure directories exist
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def is_system_idle(self) -> bool:
        """Check if CPU and Memory usage are below the idle thresholds."""
        cpu_usage = psutil.cpu_percent(interval=0.5)
        mem_usage = psutil.virtual_memory().percent
        print(f"[{datetime.now()}] System resource check: CPU: {cpu_usage}%, Memory: {mem_usage}%")
        return cpu_usage < config.cpu_threshold and mem_usage < config.memory_threshold

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

    def get_ollama_embedding(self, text: str) -> list[float]:
        """Fetch vector embedding for the description using Ollama."""
        try:
            url = f"{config.ollama_host}/api/embeddings"
            payload = {"model": config.embedding_model, "prompt": text}
            resp = requests.post(url, json=payload, timeout=5.0)
            if resp.status_code == 200:
                return resp.json().get("embedding", [])
        except Exception as e:
            print(f"Error generating embedding from Ollama: {e}")

        # Fallback to zero vector if embedding fails (to prevent pipeline crash)
        dim = db.get_embedding_dimension()
        return [0.0] * dim

    def extract_ocr_text(self, img_path: Path) -> str:
        """Call local Ollama OCR model to extract all readable text from screenshot."""
        try:
            print(f"[{datetime.now()}] Running OCR on screenshot using model: {config.ocr_model}")
            client = ollama.Client(host=config.ollama_host)
            prompt = "Extract all readable text, titles, labels, or content from this desktop screenshot exactly as shown. Do not explain, describe, or add any meta-commentary. Just output the extracted text."
            response = client.chat(
                model=config.ocr_model,
                messages=[{"role": "user", "content": prompt, "images": [str(img_path)]}],
                options={"temperature": 0.1},
            )
            ocr_text = response.get("message", {}).get("content", "").strip()
            print(f"[{datetime.now()}] OCR Extracted text length: {len(ocr_text)}")
            return ocr_text
        except Exception as e:
            print(f"Error running OCR with Ollama model {config.ocr_model}: {e}")
            return ""

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
        try:
            print(f"[{datetime.now()}] Processing pending screenshot: {img_path.name}")

            # Load metadata context
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            app_name = metadata.get("app_name", "Unknown")
            window_title = metadata.get("window_title", "Unknown")

            # 1. Run OCR extraction
            ocr_text = self.extract_ocr_text(img_path)

            # 2. Get unique tags for tag reuse
            existing_tags = db.get_all_unique_tags()
            if len(existing_tags) > 100:
                existing_tags = existing_tags[:100]  # Cap for prompt efficiency

            projects_str = json.dumps(projects, indent=2, ensure_ascii=False)

            # Prompt for Ollama vision model
            prompt_text = f"""
You are an advanced automated time-tracking and productivity classification assistant.
Analyze the provided screenshot of the user's desktop screen and combine it with this metadata context:
- Active Application: {app_name}
- Active Window Title: {window_title}
- Extracted Screen Text (OCR): {ocr_text}

We also have a list of active work projects:
{projects_str}

We have a list of existing tags in our system:
{existing_tags}

Analyze the screenshot carefully to identify what the user is working on, the topic, visible text, code, or browser content.
Follow these context-specific rules for your analysis to be less generic:
1. **Jira, GitLab, or Kanban Boards**: Identify specific ticket numbers (e.g., "PRJ-2026-042" or similar), column names (To Do, In Progress, Done), ticket types (bug, feature, task, discussion), and their specific content.
2. **Chats (Slack, Teams, Discord, etc.)**: Note the conversation partner's name or channel and the specific topic/matter being discussed.
3. **IDE or Coding (VS Code, Cursor, terminal, etc.)**: Identify the programming language, files open, functions or classes being written, and any bugs/errors shown.

Generate a JSON object containing:
1. "description": A highly detailed, granular single-paragraph description of the active task, specific content, website URLs, search terms, code structure, or topic. Include ticket numbers, chat partners, file names, or languages if present.
2. "tags": A list of 3 to 7 relevant tags/keywords (e.g. ["python", "vector-db", "welding", "woodworking", "research"]). REUSE existing tags from the list provided above whenever they are a good match. Only generate a brand new tag if none of the existing tags accurately represent the work.
3. "project_number": Choose the project_number from the active work projects list that fits this activity based on its description and work entailment. If none of the projects are a fit, output "None". Be conservative: only match if the screenshot content and window context strongly correlate with the project description.

You MUST respond in valid JSON format.
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

            # Call Ollama chat vision endpoint
            client = ollama.Client(host=config.ollama_host)
            response = client.chat(
                model=config.vision_model,
                messages=[{"role": "user", "content": prompt_text, "images": [str(vision_img_path)]}],
                format="json",
                options={"temperature": 0.2},
            )

            # Parse JSON response
            raw_response = response.get("message", {}).get("content", "")
            print(f"Ollama Vision response: {raw_response}")

            parsed = json.loads(raw_response)
            description = parsed.get("description", "No description generated.")
            tags = parsed.get("tags", [])
            project_number = parsed.get("project_number", "None")
            if project_number == "None":
                project_number = None

            # 3. Get embedding of the combined description & OCR text
            embedding_text = f"Description: {description}\n\nExtracted Screen Text:\n{ocr_text}"
            embedding = self.get_ollama_embedding(embedding_text)

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
            db.insert_screenshot(db_record)

            # Move image & metadata to processed directory
            shutil.move(str(img_path), str(self.processed_dir / img_path.name))
            if full_img_path.exists():
                shutil.move(str(full_img_path), str(self.processed_dir / full_img_filename))
            meta_path.unlink()  # Delete temporary raw metadata JSON file

            print(f"[{datetime.now()}] Successfully processed screenshot. Classified as project: {project_number}")
            return True

        except Exception as e:
            print(f"Error processing screenshot {img_path.name}: {e}")
            traceback.print_exc()
            return False

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
