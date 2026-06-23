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
from aw_vision.embedding import build_embedding_text, generate_embedding


def caveman_compress_text(text: str) -> str:
    """Algorithmically compress text in a caveman style by stripping filler words and duplicate lines."""
    if not text or text == "N/A":
        return text

    # Split into lines, normalize whitespace, and filter empty lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Filter common stop words to make each line dense and terse
    filler_words = {
        "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
        "to", "of", "in", "on", "at", "by", "for", "with", "about", "against", "between", "into",
        "through", "during", "before", "after", "above", "below", "from", "up", "down", "in", "out",
        "off", "over", "under", "again", "further", "then", "once"
    }

    compressed_lines = []
    seen = set()
    for line in lines:
        words = line.split()
        compressed_words = [w for w in words if w.lower() not in filler_words]
        if compressed_words:
            compressed_line = " ".join(compressed_words)
            norm = compressed_line.lower()
            if norm not in seen:
                seen.add(norm)
                compressed_lines.append(compressed_line)

    return " | ".join(compressed_lines)


class BulkProcessor:
    def __init__(self):
        self.raw_dir = config.screenshots_dir / "raw"
        self.processed_dir = config.screenshots_dir / "processed"
        self.running = False
        self.is_processing = False
        self.current_batch_total = 0
        self.current_batch_processed = 0
        self.current_rec_id = None
        self.current_stage = None
        self.last_error = None
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

    def get_embedding(self, text: str, img_path: str = None, rec_id: str = None, keep_alive: int = 300) -> list[float]:
        """Fetch a vector embedding via the configured provider, routing progress to processing logs.

        Thin wrapper over :func:`aw_vision.embedding.generate_embedding`; the embedding logic lives
        in the dedicated ``embedding`` module so it can be reused by query paths and migrations.
        """
        return generate_embedding(
            text,
            img_path=img_path,
            rec_id=rec_id,
            keep_alive=keep_alive,
            log=self.log_step,
        )

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

    def summarize_ocr_text(self, ocr_text: str, max_chars: int = 1200) -> str:
        """Pre-process, compress using Caveman style, and truncate OCR text to fit within constraints."""
        if not ocr_text:
            return ""

        compressed = caveman_compress_text(ocr_text)
        if len(compressed) <= max_chars:
            return compressed

        # Truncate and append truncation message
        truncated = compressed[:max_chars]
        last_pipe = truncated.rfind(" | ")
        if last_pipe > max_chars // 2:
            truncated = truncated[:last_pipe]

        return truncated + f" ... [OCR Text truncated from {len(compressed)} to {len(truncated)} chars]"

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
            bucket_id = f"aw-watcher-vision_{hostname}"

            # Ensure bucket exists (aw-server handles 304 or 200)
            url_create = f"http://localhost:5600/api/0/buckets/{bucket_id}"
            create_payload = {
                "client": "aw-watcher-vision",
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
        """Process a list of raw screenshot and metadata tuples sequentially in distinct stages, chunked into smaller groups to prevent UI freezing and commit progressively."""
        with self.lock:
            if self.is_processing:
                print(f"[{datetime.now()}] [BulkProcessor] A batch processing run is already active. Skipping.")
                return False
            self.is_processing = True
            self.current_batch_total = len(queue)
            self.current_batch_processed = 0
            self.current_rec_id = None
            self.current_stage = "Initializing batch..."
            self.last_error = None

        from aw_vision.settings import settings_store
        provider = settings_store.get("provider") or "gemini"

        # Determine chunk size dynamically:
        # - Cloud-primary mode (Gemini): chunk_size = 1 so every item is fully processed and committed immediately to LanceDB (gives instant UI updates)
        # - Mixed/Local mode (Ollama involved): chunk_size = 10 to balance model-swapping overhead with progressive commits.
        if provider == "gemini":
            chunk_size = 1
        else:
            chunk_size = 10

        chunks = [queue[i:i + chunk_size] for i in range(0, len(queue), chunk_size)]

        overall_success = False
        try:
            for chunk_idx, chunk in enumerate(chunks):
                print(f"[{datetime.now()}] [BulkProcessor] Processing chunk {chunk_idx + 1}/{len(chunks)} of size {len(chunk)}...")
                batch_items = []
                try:
                    success = self._process_batch_impl(chunk, projects, batch_items)
                    if success:
                        overall_success = True
                finally:
                    # Clean up processing_ids for this completed chunk immediately so UI can update and fetch them
                    with self.lock:
                        for item in batch_items:
                            rec_id = item[2]
                            self.processing_ids.discard(rec_id)
            return overall_success
        finally:
            with self.lock:
                self.is_processing = False
                self.current_rec_id = None
                self.current_stage = None

    def _process_batch_impl(self, queue: list[tuple[Path, Path]], projects: list, batch_items: list) -> bool:
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

        failed_ids = set()
        N = len(batch_items)
        print(f"[{datetime.now()}] Batch-processing {N} screenshots in staged sweeps...")

        # -------------------------------------------------------------
        # Phase 1: Optimize & OCR Sweep
        # -------------------------------------------------------------
        for idx, (img_path, meta_path, rec_id, meta) in enumerate(batch_items):
            with self.lock:
                self.current_rec_id = rec_id
                self.current_stage = f"Phase 1/3 (OCR Extraction): Item {self.current_batch_processed + idx + 1}/{self.current_batch_total}"
            try:
                ocr_start = time.time()
                self.log_step(rec_id, f"Phase 1/3: Image Optimization & OCR extraction (item {idx + 1}/{N} in batch)")

                # Image optimization
                full_img_filename = f"{img_path.stem}_full.png"
                full_img_path = img_path.parent / full_img_filename

                self.optimize_image(img_path, rec_id, max_size=1200)
                if full_img_path.exists():
                    self.optimize_image(full_img_path, rec_id, max_size=1200)

                # Only run OCR if not already cached
                if "ocr_text" not in meta or meta["ocr_text"] is None:
                    from aw_vision.settings import settings_store
                    from aw_vision.gemini import is_internet_online, run_gemini_ocr
                    provider = settings_store.get("provider") or "gemini"
                    ocr_provider = settings_store.get("ocr_provider") or "ollama"
                    internet_online = is_internet_online()

                    if provider == "gemini" and ocr_provider == "gemini" and internet_online:
                        self.log_step(rec_id, "Both main and OCR providers are Gemini & online. Skipping Phase 1 OCR; will run combined Gemini OCR + Vision in Phase 2.")
                        meta["duration_ocr"] = 0.0
                    elif ocr_provider == "gemini" and internet_online:
                        self.log_step(rec_id, "Running Cloud OCR using Gemini...")
                        try:
                            ocr_text = run_gemini_ocr(img_path)
                            meta["ocr_text"] = ocr_text
                            meta["duration_ocr"] = time.time() - ocr_start
                            with open(meta_path, "w", encoding="utf-8") as f:
                                json.dump(meta, f, indent=2)
                            self.log_step(rec_id, f"Cloud OCR complete. Length: {len(ocr_text)}")
                        except Exception as ocr_err:
                            self.log_step(rec_id, f"Error running Cloud Gemini OCR, falling back to local Ollama: {ocr_err}")
                            keep_alive = 0 if (idx == N - 1) else 300
                            ocr_text = self.extract_ocr_text(img_path, rec_id, keep_alive=keep_alive)
                            meta["ocr_text"] = ocr_text
                            meta["duration_ocr"] = time.time() - ocr_start
                            with open(meta_path, "w", encoding="utf-8") as f:
                                json.dump(meta, f, indent=2)
                    else:
                        # Keep model loaded during the sweep, unload immediately on the last item of Phase 1
                        keep_alive = 0 if (idx == N - 1) else 300
                        ocr_text = self.extract_ocr_text(img_path, rec_id, keep_alive=keep_alive)
                        meta["ocr_text"] = ocr_text
                        meta["duration_ocr"] = time.time() - ocr_start

                        # Persist ocr_text to the metadata JSON file on disk
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump(meta, f, indent=2)
                else:
                    self.log_step(rec_id, "OCR text already cached in metadata JSON. Skipping OCR.")
                    if "duration_ocr" not in meta:
                        meta["duration_ocr"] = 0.0
            except Exception as e:
                self.log_step(rec_id, f"Error in Phase 1 (OCR) for {img_path.name}: {e}")
                with self.lock:
                    self.last_error = f"Phase 1 error for {rec_id}: {e}"

        # -------------------------------------------------------------
        # Phase 2: Vision Analysis Sweep (6-stage sequential multi-prompt pipeline)
        # -------------------------------------------------------------
        for idx, (img_path, meta_path, rec_id, meta) in enumerate(batch_items):
            with self.lock:
                self.current_rec_id = rec_id
                self.current_stage = f"Phase 2/3 (Vision Analysis): Item {self.current_batch_processed + idx + 1}/{self.current_batch_total}"
            try:
                vision_start = time.time()
                self.log_step(rec_id, f"Phase 2/3: Vision model analysis & Project classification (item {idx + 1}/{N} in batch)")

                # Only run Vision if not already processed (meaning we don't have description)
                if "description" not in meta or meta["description"] is None:
                    full_img_filename = f"{img_path.stem}_full.png"
                    full_img_path = img_path.parent / full_img_filename

                    from aw_vision.settings import settings_store
                    from aw_vision.gemini import run_gemini_combined_ocr_vision, is_internet_online
                    use_gemini = (settings_store.get("provider") == "gemini" and is_internet_online())

                    if use_gemini:
                        cached_ocr = meta.get("ocr_text")
                        if cached_ocr:
                            self.log_step(rec_id, "Running Gemini Vision analysis with pre-extracted OCR text...")
                        else:
                            self.log_step(rec_id, "Running combined Gemini OCR and Vision analysis...")
                        existing_tags = db.get_all_unique_tags()
                        if len(existing_tags) > 100:
                            existing_tags = existing_tags[:100]
                        try:
                            res = run_gemini_combined_ocr_vision(
                                img_path=img_path,
                                full_img_path=full_img_path if full_img_path.exists() else None,
                                projects=projects,
                                existing_tags=existing_tags,
                                ocr_text=cached_ocr if cached_ocr else None
                            )
                            meta["ocr_text"] = res.get("ocr_text", "") or cached_ocr or ""
                            meta["description"] = res.get("description", "No description generated.")
                            meta["tags"] = res.get("tags", [])
                            meta["project_number"] = res.get("project_number", "None")
                            meta["unique_things"] = res.get("unique_things", "None detected.")
                            meta["vector"] = []  # Generated in Phase 3
                            meta["duration_vision"] = time.time() - vision_start

                            # Persist results to metadata JSON file on disk
                            with open(meta_path, "w", encoding="utf-8") as f:
                                json.dump(meta, f, indent=2)

                            self.log_step(rec_id, f"Gemini Combined Analysis complete. Description: {meta['description']}")
                            continue
                        except Exception as eg:
                            self.log_step(rec_id, f"Error calling Gemini, falling back to local Ollama: {eg}")

                    aw_context_str = "None"
                    bucket_context = meta.get("aw_bucket_context", {})
                    if bucket_context:
                        aw_context_str = json.dumps(bucket_context, indent=2, ensure_ascii=False)

                    existing_tags = db.get_all_unique_tags()
                    if len(existing_tags) > 100:
                        existing_tags = existing_tags[:100]

                    projects_str = json.dumps(projects, indent=2, ensure_ascii=False)

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

                    raw_ocr = meta.get("ocr_text", "")
                    truncated_ocr = self.summarize_ocr_text(raw_ocr, max_chars=1200)

                    client = ollama.Client(host=config.ollama_host)

                    stage_keep_alive = 300
                    final_keep_alive = 0 if (idx == N - 1) else 300

                    # ---------------------------------------------------------
                    # Pass 1/2: Single multimodal vision call.
                    # Collapses the former Stages 1, 2 & 6 (active window, desktop
                    # context, unique artifacts) into ONE inference over both crops,
                    # encoding each image at most once instead of three times.
                    # ---------------------------------------------------------
                    active_window_description = "No active window description generated."
                    full_desktop_description = "No fullscreen desktop context available."
                    unique_things = "None detected."
                    has_full = full_img_path.exists()
                    try:
                        self.log_step(rec_id, "Vision pass 1/2: Analyzing focused window, desktop context & unique artifacts...")
                        images_v = [str(img_path)]
                        if has_full:
                            images_v.append(str(full_img_path))
                        prompt_v = (
                            "Analyze the attached desktop screenshot(s). "
                            + (
                                "The FIRST image is the focused foreground window; the SECOND is the full background desktop context. "
                                if has_full
                                else "The image is the focused foreground window. "
                            )
                            + "Be highly objective, granular, and precise. Specify filenames, code functions, browser URLs, "
                            "searched keywords, active spreadsheet columns, or chat messages. Do not add conversational filler "
                            "or generic assumptions.\n\n"
                            "You must respond in valid JSON format matching this schema:\n"
                            "{\n"
                            '  "active_window_description": "what the focused foreground window/document/workspace shows",\n'
                            '  "full_desktop_description": "peripheral/background windows, sidebars or layout OUTSIDE the focus (keep brief if none)",\n'
                            '  "unique_things": "specific terminal commands, active code blocks, file paths, specialized widgets or tools present"\n'
                            "}"
                        )
                        response_v = client.chat(
                            model=config.vision_model,
                            messages=[{"role": "user", "content": prompt_v, "images": images_v}],
                            format="json",
                            options={"temperature": 0.2, "num_ctx": 8192},
                            keep_alive=stage_keep_alive,
                        )
                        parsed_v = json.loads(response_v.get("message", {}).get("content", "") or "{}")
                        active_window_description = (parsed_v.get("active_window_description") or "").strip() or active_window_description
                        full_desktop_description = (parsed_v.get("full_desktop_description") or "").strip() or full_desktop_description
                        unique_things = (parsed_v.get("unique_things") or "").strip() or unique_things
                        self.log_step(rec_id, f"Vision pass complete: {active_window_description[:120]}...")
                    except Exception as ev:
                        self.log_step(rec_id, f"Warning: Vision pass failed: {ev}")
                        active_window_description = f"Error analyzing screenshot: {ev}"

                    # ---------------------------------------------------------
                    # Pass 2/2: Single text-only synthesis call.
                    # Collapses the former Stages 3, 4 & 5 (project classification,
                    # tag generation, caveman-style description) into ONE inference.
                    # ---------------------------------------------------------
                    project_number = "None"
                    tags = []
                    description = "No description generated."
                    try:
                        self.log_step(rec_id, "Vision pass 2/2: Classifying project, generating tags & synthesizing description...")

                        # Query historically similar snapshots using metadata overlap instead of vector embeddings to prevent model swapping
                        similar_snapshots = db.get_similar_labeled_snapshots_by_metadata(
                            app_name=meta.get("app_name"),
                            window_title=meta.get("window_title"),
                            limit=5
                        )
                        similar_snapshots_str = json.dumps(similar_snapshots, ensure_ascii=False)

                        prompt_syn = f"""
You are indexing a desktop snapshot. Use only the evidence below.
- Active Window: {active_window_description}
- Desktop Context: {full_desktop_description}
- Unique Artifacts: {unique_things}
- Extracted Screen Text (OCR): {truncated_ocr}
- ActivityWatch Bucket State: {aw_context_str}
- Neighboring Snapshots: {neighbor_context_str}
- Historically Similar Snapshots: {similar_snapshots_str}
- App project statistics: {app_freq_str}

Project Reference Catalog:
{projects_str}

Produce exactly three outputs:
1. project_number: classify this activity into ONE catalog project. Be extremely conservative: if there is no strong, explicit, and direct evidence correlating the active screen contents to a project's description/entailment, output "None". Do NOT match on inactive sidebar chats, adjacent tab names, browser bookmarks, or external company profiles. Stay consistent with neighbor and human-labeled snapshots when they form a continuous block of activity on the same application.
2. tags: 3 to 7 highly relevant, technical tags/keywords for this task. Prioritize reusing these existing database tags for consistency: {existing_tags}
3. description: an ultra-dense, highly precise "Caveman-style" work summary. Omit filler words (the, a, is, was, were, to, of, for); use dense technical fragments separated by semicolons/periods. Every word must carry maximum technical information.
   Example: "Dev aw-vision UI. Refactored list component; displaying unique elements via exact CSS tokens."

You must respond in valid JSON format matching this exact schema:
{{
  "project_number": "string (catalog project number, or \\"None\\")",
  "tags": ["string"],
  "description": "string"
}}
"""
                        response_syn = client.chat(
                            model=config.vision_model,
                            messages=[{"role": "user", "content": prompt_syn}],
                            format="json",
                            options={"temperature": 0.2, "num_ctx": 8192},
                            keep_alive=final_keep_alive,
                        )
                        parsed_syn = json.loads(response_syn.get("message", {}).get("content", "") or "{}")
                        project_number = (parsed_syn.get("project_number") or "None").strip() or "None"
                        syn_tags = parsed_syn.get("tags", [])
                        tags = syn_tags if isinstance(syn_tags, list) else []
                        description = (parsed_syn.get("description") or "").strip() or description
                        self.log_step(rec_id, f"Synthesis complete: Project='{project_number}', Tags={tags}, Desc={description[:120]}...")
                    except Exception as esyn:
                        self.log_step(rec_id, f"Warning: Synthesis pass failed: {esyn}")

                    # Assign results to meta dictionary
                    meta["description"] = description
                    meta["tags"] = tags
                    meta["project_number"] = project_number
                    meta["unique_things"] = unique_things
                    meta["duration_vision"] = time.time() - vision_start

                    # Persist results to metadata JSON file on disk
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=2)
                else:
                    self.log_step(rec_id, "Vision analysis results already cached in metadata. Skipping vision model.")
                    if "duration_vision" not in meta:
                        meta["duration_vision"] = 0.0
            except Exception as e:
                self.log_step(rec_id, f"Error in Phase 2 (Vision) for {img_path.name}: {e}\n{traceback.format_exc()}")
                failed_ids.add(rec_id)
                with self.lock:
                    self.last_error = f"Phase 2 error for {rec_id}: {e}"

        # -------------------------------------------------------------
        # Phase 3: Embeddings & DB Commit Sweep
        # -------------------------------------------------------------
        success_count = 0
        for idx, (img_path, meta_path, rec_id, meta) in enumerate(batch_items):
            with self.lock:
                self.current_rec_id = rec_id
                self.current_stage = f"Phase 3/3 (Database Commit): Item {self.current_batch_processed + 1}/{self.current_batch_total}"
            try:
                if rec_id in failed_ids:
                    self.log_step(rec_id, "Skipping Phase 3/3 due to previous failures in Phase 2.")
                    continue

                self.log_step(rec_id, f"Phase 3/3: Embedding calculation, DB commit & Cleanup (item {idx + 1}/{N} in batch)")

                description = meta.get("description", "No description generated.")
                ocr_text = self.summarize_ocr_text(meta.get("ocr_text", ""), max_chars=1200)
                tags = meta.get("tags", [])
                project_number = meta.get("project_number", "None")
                if project_number == "None":
                    project_number = None

                embedding = meta.get("vector")
                if not embedding or len(embedding) == 0:
                    emb_start = time.time()
                    # Build a right-sized, text-only embedding input (no full image bytes) that
                    # includes high-signal metadata for better semantic retrieval.
                    embedding_text = build_embedding_text({
                        "app_name": meta.get("app_name"),
                        "window_title": meta.get("window_title"),
                        "description": description,
                        "project_number": meta.get("project_number"),
                        "tags": tags,
                        "ocr_text": ocr_text,
                    })
                    keep_alive = 0 if (idx == N - 1) else 300
                    # Pass the focused screenshot; get_embedding only forwards it to
                    # multimodal-capable embedding models (e.g. gemini-embedding-2).
                    embedding = self.get_embedding(
                        embedding_text,
                        img_path=str(img_path),
                        rec_id=rec_id,
                        keep_alive=keep_alive
                    )
                    meta["duration_embedding"] = time.time() - emb_start
                else:
                    if "duration_embedding" not in meta:
                        meta["duration_embedding"] = 0.0

                duration_ocr = meta.get("duration_ocr", 0.0)
                duration_vision = meta.get("duration_vision", 0.0)
                duration_embedding = meta.get("duration_embedding", 0.0)
                duration_total = duration_ocr + duration_vision + duration_embedding
                meta["duration_total"] = duration_total

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
                    "unique_things": meta.get("unique_things"),
                    "vector": embedding,
                    "duration_ocr": meta.get("duration_ocr"),
                    "duration_vision": meta.get("duration_vision"),
                    "duration_embedding": meta.get("duration_embedding"),
                    "duration_total": meta.get("duration_total"),
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
                with self.lock:
                    self.last_error = f"Phase 3 error for {rec_id}: {e}"
                try:
                    log_file = img_path.parent / f"{rec_id}.log"
                    with open(log_file, "w", encoding="utf-8") as lf:
                        lf.write("\n".join(self.processing_logs.get(rec_id, [])))
                except Exception as le:
                    print(f"Error saving raw log file: {le}")
                traceback.print_exc()
            finally:
                with self.lock:
                    self.current_batch_processed += 1

        return success_count > 0

    def process_screenshot(self, img_path: Path, meta_path: Path, projects: list) -> bool:
        """Process a single screenshot by wrapping it as a batch of 1 and calling process_batch."""
        return self.process_batch([(img_path, meta_path)], projects)

    def force_process_all(self):
        """Force process all pending items immediately in an optimized background batch thread."""
        with self.lock:
            if self.is_processing:
                print(f"[{datetime.now()}] [BulkProcessor] A batch processing run is already active. Skipping force_process_all.")
                return

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

                with self.lock:
                    is_proc = self.is_processing

                if is_proc:
                    # Already processing, skip this loop iteration
                    pass
                else:
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
