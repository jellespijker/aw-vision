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
        """Fetch vector embedding for the description using configured provider (Gemini or Ollama)."""
        from aw_vision.settings import settings_store
        from aw_vision.gemini import generate_gemini_embedding, is_internet_online

        provider = settings_store.get("provider")
        use_gemini = (provider == "gemini" and is_internet_online())

        embedding = []
        if use_gemini:
            try:
                embedding = generate_gemini_embedding(text)
            except Exception as e:
                err_msg = f"Error generating Gemini embedding: {e}. Falling back to Ollama."
                if rec_id:
                    self.log_step(rec_id, err_msg)
                else:
                    print(err_msg)

        if not embedding:
            try:
                model = settings_store.get("ollama_embedding_model") or config.embedding_model
                url = f"{config.ollama_host}/api/embeddings"
                payload = {"model": model, "prompt": text, "keep_alive": 0}
                resp = requests.post(url, json=payload, timeout=30.0)
                if resp.status_code == 200:
                    embedding = resp.json().get("embedding", [])
            except Exception as e:
                err_msg = f"Error generating embedding from Ollama: {e}"
                if rec_id:
                    self.log_step(rec_id, err_msg)
                else:
                    print(err_msg)

        expected_dim = db.get_embedding_dimension()
        if not embedding:
            return [0.0] * expected_dim

        # Pad or truncate to expected dimension
        if len(embedding) < expected_dim:
            embedding = list(embedding) + [0.0] * (expected_dim - len(embedding))
        elif len(embedding) > expected_dim:
            embedding = list(embedding)[:expected_dim]

        return embedding

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
        """Process a list of raw screenshot and metadata tuples sequentially in distinct stages to limit Ollama model load/unload cycles."""
        with self.lock:
            if self.is_processing:
                print(f"[{datetime.now()}] [BulkProcessor] A batch processing run is already active. Skipping.")
                return False
            self.is_processing = True

        batch_items = []
        try:
            return self._process_batch_impl(queue, projects, batch_items)
        finally:
            with self.lock:
                self.is_processing = False
                for item in batch_items:
                    rec_id = item[2]
                    self.processing_ids.discard(rec_id)

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
                    from aw_vision.settings import settings_store
                    from aw_vision.gemini import is_internet_online
                    use_gemini = (settings_store.get("provider") == "gemini" and is_internet_online())

                    if use_gemini:
                        self.log_step(rec_id, "Gemini provider is active & online. Skipping local OCR; will run combined Gemini OCR + Vision in Phase 2.")
                    else:
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
        # Phase 2: Vision Analysis Sweep (6-stage sequential multi-prompt pipeline)
        # -------------------------------------------------------------
        for idx, (img_path, meta_path, rec_id, meta) in enumerate(batch_items):
            try:
                self.log_step(rec_id, f"Phase 2/3: Vision model analysis & Project classification (item {idx + 1}/{N} in batch)")

                # Only run Vision if not already processed (meaning we don't have description)
                if "description" not in meta or meta["description"] is None:
                    full_img_filename = f"{img_path.stem}_full.png"
                    full_img_path = img_path.parent / full_img_filename

                    from aw_vision.settings import settings_store
                    from aw_vision.gemini import run_gemini_combined_ocr_vision, is_internet_online
                    use_gemini = (settings_store.get("provider") == "gemini" and is_internet_online())

                    if use_gemini:
                        self.log_step(rec_id, "Running combined Gemini OCR and Vision analysis...")
                        existing_tags = db.get_all_unique_tags()
                        if len(existing_tags) > 100:
                            existing_tags = existing_tags[:100]
                        try:
                            res = run_gemini_combined_ocr_vision(
                                img_path=img_path,
                                full_img_path=full_img_path if full_img_path.exists() else None,
                                projects=projects,
                                existing_tags=existing_tags
                            )
                            meta["ocr_text"] = res.get("ocr_text", "")
                            meta["description"] = res.get("description", "No description generated.")
                            meta["tags"] = res.get("tags", [])
                            meta["project_number"] = res.get("project_number", "None")
                            meta["unique_things"] = res.get("unique_things", "None detected.")
                            meta["vector"] = []  # Generated in Phase 3

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

                    # --- Stage 1: Active Window Description ---
                    active_window_description = "No active window description generated."
                    try:
                        self.log_step(rec_id, "Stage 1/6: Analyzing Active Window focused crop...")
                        prompt_s1 = (
                            "Describe exactly what window, application document, or active workspace section is open, "
                            "focusing ONLY on the focused foreground window content. Be highly objective, granular, and precise. "
                            "Specify filenames, code functions, browser URLs, searched keywords, active spreadsheet columns, or chat messages. "
                            "Do not explain background context, make generic assumptions, or add conversational filler. "
                            "Just describe the active focused foreground window elements visible.\n\n"
                            "You must respond in valid JSON format matching this schema:\n"
                            '{\n  "active_window_description": "string"\n}'
                        )
                        response_s1 = client.chat(
                            model=config.vision_model,
                            messages=[{"role": "user", "content": prompt_s1, "images": [str(img_path)]}],
                            format="json",
                            options={"temperature": 0.2, "num_ctx": 8192},
                            keep_alive=stage_keep_alive,
                        )
                        raw_s1 = response_s1.get("message", {}).get("content", "")
                        parsed_s1 = json.loads(raw_s1)
                        active_window_description = parsed_s1.get("active_window_description", "").strip() or active_window_description
                        self.log_step(rec_id, f"Stage 1 Complete: {active_window_description[:120]}...")
                    except Exception as es1:
                        self.log_step(rec_id, f"Warning: Stage 1 failed: {es1}")
                        active_window_description = f"Error analyzing active window focused crop: {es1}"

                    # --- Stage 2: Full Desktop Context ---
                    full_desktop_description = "No fullscreen desktop context available."
                    if full_img_path.exists():
                        try:
                            self.log_step(rec_id, "Stage 2/6: Analyzing Full Desktop Context...")
                            prompt_s2 = (
                                "Describe any supplementary or peripheral windows, background apps, desktop workspace layout, "
                                "or sidebars as supplementary context. Focus only on things OUTSIDE the active focused window. "
                                "If no other relevant windows or context exist, keep it very brief.\n\n"
                                "You must respond in valid JSON format matching this schema:\n"
                                '{\n  "full_desktop_description": "string"\n}'
                            )
                            response_s2 = client.chat(
                                model=config.vision_model,
                                messages=[{"role": "user", "content": prompt_s2, "images": [str(full_img_path)]}],
                                format="json",
                                options={"temperature": 0.2, "num_ctx": 8192},
                                keep_alive=stage_keep_alive,
                            )
                            raw_s2 = response_s2.get("message", {}).get("content", "")
                            parsed_s2 = json.loads(raw_s2)
                            full_desktop_description = parsed_s2.get("full_desktop_description", "").strip() or full_desktop_description
                            self.log_step(rec_id, f"Stage 2 Complete: {full_desktop_description[:120]}...")
                        except Exception as es2:
                            self.log_step(rec_id, f"Warning: Stage 2 failed: {es2}")
                            full_desktop_description = f"Error analyzing full desktop context: {es2}"
                    else:
                        self.log_step(rec_id, "Stage 2/6: Skipped (no fullscreen desktop image).")

                    # --- Stage 3: Project Classification ---
                    project_number = "None"
                    query_vector = []
                    try:
                        self.log_step(rec_id, "Stage 3/6: Retrieving semantic neighbor context & running Project Classification...")
                        # Compute quick query vector using generated active window description & OCR text
                        query_text = f"Description: {active_window_description}\n\nExtracted Screen Text:\n{truncated_ocr}"
                        query_vector = self.get_ollama_embedding(query_text, rec_id=rec_id)

                        # Query historically similar snapshots
                        similar_snapshots = db.get_similar_labeled_snapshots(
                            vector=query_vector,
                            tags=None,
                            app_name=meta.get("app_name"),
                            limit=5
                        )
                        similar_snapshots_str = json.dumps(similar_snapshots, indent=2, ensure_ascii=False)

                        projects_str = json.dumps(projects, indent=2, ensure_ascii=False)

                        prompt_s3 = f"""
Compare the following information:
- Active Window Description: {active_window_description}
- Full Desktop Description: {full_desktop_description}
- Extracted Screen Text (OCR): {truncated_ocr}
- ActivityWatch Bucket State: {aw_context_str}
- Neighboring Snapshots context: {neighbor_context_str}
- Historically Similar Snapshots: {similar_snapshots_str}
- App project statistics: {app_freq_str}

Your task is to classify this activity into one of the following active projects from the Project Reference Catalog:
{projects_str}

CRITICAL RULES:
1. Be extremely conservative and precise when matching projects. If there is no strong, explicit, and direct evidence correlating the active screen contents to a project's description/entailment, you MUST output "None".
2. Do NOT match a project just because the word or name appears in an inactive sidebar chat title, adjacent tab name, or browser bookmark.
3. Do NOT assume that external company profiles are related to the user's active development projects.
4. Stay consistent with neighbor contexts and historically similar/human-labeled snapshots if they represent a continuous block of activity on the same application.

You must respond in valid JSON format matching this schema:
{{
  "project_number": "string"
}}
(Use "None" if no project matches)
"""
                        # Pure text-based prompt
                        response_s3 = client.chat(
                            model=config.vision_model,
                            messages=[{"role": "user", "content": prompt_s3}],
                            format="json",
                            options={"temperature": 0.1, "num_ctx": 8192},
                            keep_alive=stage_keep_alive,
                        )
                        raw_s3 = response_s3.get("message", {}).get("content", "")
                        parsed_s3 = json.loads(raw_s3)
                        project_number = parsed_s3.get("project_number", "None").strip() or "None"
                        self.log_step(rec_id, f"Stage 3 Complete: Matched Project = '{project_number}'")
                    except Exception as es3:
                        self.log_step(rec_id, f"Warning: Stage 3 failed: {es3}")
                        project_number = "None"

                    # --- Stage 4: Tag Generation ---
                    tags = []
                    try:
                        self.log_step(rec_id, "Stage 4/6: Generating technical tags...")
                        prompt_s4 = f"""
Based on the following desktop screenshot context:
- Active Window Description: {active_window_description}
- Full Desktop Description: {full_desktop_description}
- Extracted Screen Text (OCR): {truncated_ocr}
- Assigned Project: {project_number}

Provide a list of 3 to 7 highly relevant, technical tags or keywords representing this active task (e.g., ["react", "api-integration", "customer-outreach", "documentation", "system-diagnostic"]).

Prioritize matches with this list of existing tags in the database to maintain consistency: {existing_tags}

You must respond in valid JSON format matching this schema:
{{
  "tags": ["string"]
}}
"""
                        # Pure text-based prompt
                        response_s4 = client.chat(
                            model=config.vision_model,
                            messages=[{"role": "user", "content": prompt_s4}],
                            format="json",
                            options={"temperature": 0.2, "num_ctx": 8192},
                            keep_alive=stage_keep_alive,
                        )
                        raw_s4 = response_s4.get("message", {}).get("content", "")
                        parsed_s4 = json.loads(raw_s4)
                        tags = parsed_s4.get("tags", [])
                        if not isinstance(tags, list):
                            tags = []
                        self.log_step(rec_id, f"Stage 4 Complete: Tags = {tags}")
                    except Exception as es4:
                        self.log_step(rec_id, f"Warning: Stage 4 failed: {es4}")
                        tags = []

                    # --- Stage 5: Work Description Synthesis ---
                    description = "No description generated."
                    try:
                        self.log_step(rec_id, "Stage 5/6: Synthesizing final work description...")
                        prompt_s5 = f"""
Synthesize all of the following intermediate details into an ultra-dense, highly precise "Caveman-style" work description (omitting pronouns, articles, and auxiliary filler verbs like 'the', 'is', 'a', 'was', 'were', 'to', 'for'). Use symbols, shorthand, and dense technical fragments separated by punctuation.

Intermediate Details:
- Active Window Description: {active_window_description}
- Full Desktop Description: {full_desktop_description}
- Extracted Screen Text (OCR): {truncated_ocr}
- ActivityWatch Context: {aw_context_str}
- Assigned Project: {project_number}
- Technical Tags: {tags}

Syntactic Rules:
1. Speak like a highly technical "caveman": use short sentences, omit non-essential filler words, and favor fragments/phrases.
2. Ensure every single word carries maximum technical information. Minimize fluff.
3. Separate distinct actions or observations with semicolons or periods.
4. Example of standard description: "Developing the frontend UI for aw-vision, refactoring the list component to display unique elements with exact CSS tokens."
5. Example of Caveman-style equivalent (DO THIS STYLE): "Dev aw-vision UI. Refactored list component; displaying unique elements via exact CSS tokens."

You must respond in valid JSON format matching this schema:
{{
  "description": "string"
}}
"""
                        # Pure text-based prompt
                        response_s5 = client.chat(
                            model=config.vision_model,
                            messages=[{"role": "user", "content": prompt_s5}],
                            format="json",
                            options={"temperature": 0.2, "num_ctx": 8192},
                            keep_alive=stage_keep_alive,
                        )
                        raw_s5 = response_s5.get("message", {}).get("content", "")
                        parsed_s5 = json.loads(raw_s5)
                        description = parsed_s5.get("description", "No description generated.").strip() or description
                        self.log_step(rec_id, f"Stage 5 Complete: Description = {description}")
                    except Exception as es5:
                        self.log_step(rec_id, f"Warning: Stage 5 failed: {es5}")
                        description = "Error synthesizing work description."

                    # --- Stage 6: Unique Scene Items ---
                    unique_things = "None detected."
                    try:
                        self.log_step(rec_id, "Stage 6/6: Extracting unique elements & tools...")
                        prompt_s6 = (
                            "Analyze both the Active Window (First Image) and Fullscreen Desktop (Second Image) screenshots. "
                            "Identify and describe any unique elements, files, specialized widgets, terminal commands, active code blocks, "
                            "or specific tools present on the screen. Summarize these items as a clear bulleted list or a concise descriptive string.\n\n"
                            "You must respond in valid JSON format matching this schema:\n"
                            '{\n  "unique_things": "string"\n}'
                        )
                        images_s6 = [str(img_path)]
                        if full_img_path.exists():
                            images_s6.append(str(full_img_path))

                        response_s6 = client.chat(
                            model=config.vision_model,
                            messages=[{"role": "user", "content": prompt_s6, "images": images_s6}],
                            format="json",
                            options={"temperature": 0.2, "num_ctx": 8192},
                            keep_alive=final_keep_alive,
                        )
                        raw_s6 = response_s6.get("message", {}).get("content", "")
                        parsed_s6 = json.loads(raw_s6)
                        unique_things = parsed_s6.get("unique_things", "").strip() or unique_things
                        self.log_step(rec_id, "Stage 6 Complete: Unique elements detected.")
                    except Exception as es6:
                        self.log_step(rec_id, f"Warning: Stage 6 failed: {es6}")
                        unique_things = "Error detecting unique elements."

                    # Assign results to meta dictionary
                    meta["description"] = description
                    meta["tags"] = tags
                    meta["project_number"] = project_number
                    meta["unique_things"] = unique_things
                    meta["vector"] = query_vector

                    # Persist results to metadata JSON file on disk
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=2)
                else:
                    self.log_step(rec_id, "Vision analysis results already cached in metadata. Skipping vision model.")
            except Exception as e:
                self.log_step(rec_id, f"Error in Phase 2 (Vision) for {img_path.name}: {e}")
                failed_ids.add(rec_id)

        # -------------------------------------------------------------
        # Phase 3: Embeddings & DB Commit Sweep
        # -------------------------------------------------------------
        success_count = 0
        for idx, (img_path, meta_path, rec_id, meta) in enumerate(batch_items):
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
                    embedding_text = f"Description: {description}\n\nExtracted Screen Text:\n{ocr_text}"
                    embedding = []

                    from aw_vision.settings import settings_store
                    from aw_vision.gemini import generate_gemini_embedding, is_internet_online
                    use_gemini = (settings_store.get("provider") == "gemini" and is_internet_online())

                    if use_gemini:
                        self.log_step(rec_id, f"Generating Gemini semantic embedding using '{settings_store.get('gemini_embedding_model')}'...")
                        try:
                            embedding = generate_gemini_embedding(embedding_text)
                        except Exception as eg_emb:
                            self.log_step(rec_id, f"Error generating Gemini embedding: {eg_emb}. Falling back to Ollama.")

                    # If Gemini embedding failed or provider is Ollama
                    if not embedding:
                        model = settings_store.get("ollama_embedding_model") or config.embedding_model
                        self.log_step(rec_id, f"Generating local semantic embedding using '{model}'...")
                        # Keep embedding model loaded during the sweep, unload on the very last item of Phase 3
                        keep_alive = 0 if (idx == N - 1) else 300
                        try:
                            url = f"{config.ollama_host}/api/embeddings"
                            payload = {"model": model, "prompt": embedding_text, "keep_alive": keep_alive}
                            resp = requests.post(url, json=payload, timeout=30.0)
                            if resp.status_code == 200:
                                embedding = resp.json().get("embedding", [])
                        except Exception as ee:
                            self.log_step(rec_id, f"Error generating embedding from Ollama: {ee}")

                # Enforce dynamic expected dimension to avoid LanceDB dimension mismatch errors
                expected_dim = db.get_embedding_dimension()
                if not embedding:
                    embedding = [0.0] * expected_dim
                else:
                    if len(embedding) < expected_dim:
                        self.log_step(rec_id, f"Correction: Padding generated vector from {len(embedding)} to {expected_dim} to match DB layout.")
                        embedding = list(embedding) + [0.0] * (expected_dim - len(embedding))
                    elif len(embedding) > expected_dim:
                        self.log_step(rec_id, f"Correction: Truncating generated vector from {len(embedding)} to {expected_dim} to match DB layout.")
                        embedding = list(embedding)[:expected_dim]

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
