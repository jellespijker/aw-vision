"""Storage retention: purge expired screenshot files and null their DB image paths."""
import time
import traceback
from datetime import datetime
from pathlib import Path

from aw_vision.config import config
from aw_vision.db import db


class RetentionMixin:
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
