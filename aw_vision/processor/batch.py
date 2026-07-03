"""Batch orchestration: queue assembly plus the OCR (Phase 1) and commit (Phase 3) sweeps."""
import json
import shutil
import time
import traceback
from datetime import datetime
from pathlib import Path

from aw_vision.config import config
from aw_vision.db import db
from aw_vision.embedding import build_embedding_text
from aw_vision.models import Snapshot


class BatchMixin:
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

    def _process_batch_impl(self, queue: list, projects: list, batch_items: list) -> bool:
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

        # Three sequential model-affinity sweeps over the batch (OCR -> Vision -> Embed/commit),
        # each extracted into a focused method to keep modules within the size budget.
        self._phase1_ocr_sweep(batch_items, N)
        self._phase2_vision_sweep(batch_items, projects, N, failed_ids)
        return self._phase3_commit_sweep(batch_items, N, failed_ids)

    def _phase1_ocr_sweep(self, batch_items, N):
        """OCR sweep: optimize images and extract screen text (cloud or local)."""
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

    def _phase3_commit_sweep(self, batch_items, N, failed_ids):
        """Embedding + LanceDB commit sweep; archives files and returns batch success."""
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
                        "user_context": meta.get("user_context"),
                        "people": meta.get("people"),
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

                # Build database record through the shared typed model
                db_record = Snapshot(
                    id=meta["id"],
                    timestamp=float(meta["timestamp"]),
                    image_path=str(self.processed_dir / img_path.name),
                    window_title=meta.get("window_title", "Unknown"),
                    app_name=meta.get("app_name", "Unknown"),
                    is_afk=bool(meta.get("is_afk", False)),
                    description=description,
                    ocr_text=ocr_text,
                    tags=tags,
                    project_number=project_number,
                    human_labeled=False,
                    unique_things=meta.get("unique_things"),
                    user_context=meta.get("user_context"),
                    analysis_reasoning=meta.get("analysis_reasoning"),
                    classification_confidence=meta.get("classification_confidence"),
                    people=meta.get("people") or [],
                    duration_ocr=meta.get("duration_ocr"),
                    duration_vision=meta.get("duration_vision"),
                    duration_embedding=meta.get("duration_embedding"),
                    duration_total=meta.get("duration_total"),
                ).to_lance(embedding)

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
