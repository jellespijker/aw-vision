import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

from aw_vision.config import config


class ScreenshotWatcher:
    def __init__(self):
        self.screenshots_dir = config.screenshots_dir
        self.raw_dir = self.screenshots_dir / "raw"
        self.processed_dir = self.screenshots_dir / "processed"

        # Ensure directories exist
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        self.running = False
        self.thread = None
        self.hostname = self._get_hostname()

    def _get_hostname(self) -> str:
        import socket

        return socket.gethostname()

    def _capture_screenshot_wayland(self, output_path: Path) -> bool:
        """KDE Wayland screenshot capture using spectacle or grim."""
        # Try spectacle (native KDE)
        try:
            # -b: background/non-interactive, -n: no notification, -o: output file
            res = subprocess.run(
                ["spectacle", "-b", "-n", "-o", str(output_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10.0,
            )
            if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return True
        except Exception:
            pass

        # Try grim (general Wayland tool)
        try:
            res = subprocess.run(
                ["grim", str(output_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            )
            if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return True
        except Exception:
            pass

        return False

    def fetch_active_window_and_afk(self) -> tuple[str, str, bool]:
        """Query aw-server to get the current window title, app name, and AFK status."""
        window_title = "Unknown"
        app_name = "Unknown"
        is_afk = False

        try:
            # Fetch buckets to find the correct window and AFK buckets
            resp = requests.get("http://localhost:5600/api/0/buckets/", timeout=2.0)
            if resp.status_code == 200:
                buckets = resp.json()

                # Find matching bucket IDs
                window_bucket_id = None
                afk_bucket_id = None

                for bid in buckets.keys():
                    if bid.startswith("aw-watcher-window"):
                        window_bucket_id = bid
                    elif bid.startswith("aw-watcher-afk"):
                        afk_bucket_id = bid

                # Fetch latest window event
                if window_bucket_id:
                    w_resp = requests.get(
                        f"http://localhost:5600/api/0/buckets/{window_bucket_id}/events?limit=1",
                        timeout=1.5,
                    )
                    if w_resp.status_code == 200:
                        events = w_resp.json()
                        if events:
                            data = events[0].get("data", {})
                            window_title = data.get("title", "Unknown")
                            app_name = data.get("app", "Unknown")

                # Fetch latest AFK event
                if afk_bucket_id:
                    a_resp = requests.get(
                        f"http://localhost:5600/api/0/buckets/{afk_bucket_id}/events?limit=1",
                        timeout=1.5,
                    )
                    if a_resp.status_code == 200:
                        events = a_resp.json()
                        if events:
                            data = events[0].get("data", {})
                            is_afk = data.get("status") == "afk"

        except Exception as e:
            print(f"Warning: Could not connect to aw-server to gather context ({e})")

        return window_title, app_name, is_afk

    def capture_cycle(self):
        """Main screenshot and context capture iteration."""
        # 1. Gather context first to check if the user is active
        window_title, app_name, is_afk = self.fetch_active_window_and_afk()

        if is_afk:
            print(f"[{datetime.now()}] User is AFK. Skipping screenshot capture cycle.")
            return

        timestamp = time.time()
        file_id = str(uuid.uuid4())

        # Save raw metadata as JSON alongside the raw image
        filename = f"{int(timestamp)}_{file_id}.png"
        raw_image_path = self.raw_dir / filename
        meta_path = self.raw_dir / f"{int(timestamp)}_{file_id}.json"

        # 2. Capture screen only if user is active
        success = self._capture_screenshot_wayland(raw_image_path)
        if not success:
            print(f"[{datetime.now()}] Screenshot capture failed.")
            return

        # 3. Write metadata file
        import json

        metadata = {
            "id": file_id,
            "timestamp": timestamp,
            "image_filename": filename,
            "window_title": window_title,
            "app_name": app_name,
            "is_afk": is_afk,
        }
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            print(f"[{datetime.now()}] Captured screenshot & metadata context: {app_name} - {window_title[:30]}")
        except Exception as e:
            print(f"Error saving metadata: {e}")

    def _loop(self):
        print(f"Watcher daemon started. Capturing every {config.screenshot_interval}s.")
        while self.running:
            start_time = time.time()
            try:
                self.capture_cycle()
            except Exception as e:
                print(f"Error in capture loop: {e}")

            # Sleep for the rest of the interval
            elapsed = time.time() - start_time
            sleep_time = max(0.1, config.screenshot_interval - elapsed)

            # Sleep in small increments to respond quickly to shutdown
            for _ in range(int(sleep_time * 10)):
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
        print("Watcher daemon stopped.")


# Instantiate watcher
watcher = ScreenshotWatcher()
