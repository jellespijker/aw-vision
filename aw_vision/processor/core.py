"""BulkProcessor: composes the processor mixins and owns the daemon lifecycle."""
import threading
import time
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from aw_vision.config import config
from aw_vision.embedding import generate_embedding
from aw_vision.processor.monitor import MonitorMixin
from aw_vision.processor.ocr import OcrMixin
from aw_vision.processor.mirror import MirrorMixin
from aw_vision.processor.retention import RetentionMixin
from aw_vision.processor.vision_sweep import VisionSweepMixin
from aw_vision.processor.batch import BatchMixin


class BulkProcessor(MonitorMixin, OcrMixin, MirrorMixin, RetentionMixin, VisionSweepMixin, BatchMixin):
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
        self.scheduler = None
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

    def _process_tick(self):
        """One CPU-aware processing check: when idle and work is pending, process the queue."""
        try:
            with self.lock:
                if self.is_processing:
                    # A batch is already running; skip this tick.
                    return

            queue = self.get_pending_queue()
            if not queue:
                # No pending files, we're fully caught up.
                return

            print(f"Pending screenshots in queue: {len(queue)}")
            # Check if system is idle before running heavy Ollama jobs
            if self.is_system_idle():
                projects = config.load_projects()
                # Process the entire queue as an optimized batch!
                self.process_batch(queue, projects)
            else:
                print("System is busy (not idle). Postponing screenshot processing.")
        except Exception as e:
            print(f"Error in processor tick: {e}")

    def _retention_tick(self):
        """Periodic storage retention cleanup pass."""
        try:
            self.run_retention_cleanup()
        except Exception as e:
            print(f"Error in retention tick: {e}")

    def start(self):
        if self.running:
            return
        self.running = True

        # Use APScheduler (per AGENTS.md "reuse high-quality libraries") instead of a
        # hand-rolled sleep loop. coalesce + max_instances=1 prevent overlapping runs.
        self.scheduler = BackgroundScheduler(daemon=True)
        self.scheduler.add_job(
            self._process_tick,
            "interval",
            seconds=max(1, config.check_interval),
            id="process_tick",
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self._retention_tick,
            "interval",
            hours=max(1, config.cleanup_interval_hours),
            id="retention_tick",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(),  # run an initial cleanup shortly after startup
        )
        self.scheduler.start()
        print(
            f"Processor scheduler started. Processing check every {config.check_interval}s; "
            f"retention cleanup every {config.cleanup_interval_hours}h."
        )

    def stop(self):
        self.running = False
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        print("Processor daemon stopped.")


# Instantiate processor
