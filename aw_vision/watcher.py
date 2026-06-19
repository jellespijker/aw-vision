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

    def _capture_screenshot_wayland(self, output_path: Path, mode: str = "active") -> bool:
        """KDE Wayland screenshot capture using spectacle or grim."""
        # Try spectacle (native KDE)
        try:
            cmd = ["spectacle"]
            if mode == "active":
                cmd.append("-a")  # Capture active window
            elif mode == "fullscreen":
                cmd.append("-f")  # Capture entire desktop
            elif mode == "current":
                cmd.append("-m")  # Capture current monitor

            # -b: background/non-interactive, -n: no notification, -o: output file
            cmd.extend(["-b", "-n", "-o", str(output_path)])

            res = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10.0,
            )
            if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return True
        except Exception:
            pass

        # Try grim (general Wayland tool) - falls back to fullscreen
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

    def fetch_active_window_and_afk(self) -> tuple[str, str, bool, dict]:
        """Query aw-server to get the current window title, app name, AFK status, and extra bucket contexts."""
        window_title = "Unknown"
        app_name = "Unknown"
        is_afk = False
        bucket_context = {}

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
                            event = events[0]
                            data = event.get("data", {})
                            status = data.get("status")
                            if status == "afk":
                                is_afk = True
                            else:
                                # Check if the last active heartbeat is stale (older than 3 minutes)
                                try:
                                    from datetime import timezone
                                    ts_str = event.get("timestamp")
                                    dur = event.get("duration", 0.0)

                                    # Parse RFC3339 timestamp robustly
                                    if ts_str.endswith("Z"):
                                        ts_str = ts_str[:-1] + "+00:00"
                                    if "." in ts_str:
                                        base, tz = ts_str.split("+")
                                        main, frac = base.split(".")
                                        frac = frac[:6]
                                        ts_str = f"{main}.{frac}+{tz}"

                                    event_time = datetime.fromisoformat(ts_str)
                                    current_time = datetime.now(timezone.utc)

                                    # Add duration to find the end of the last active event
                                    from datetime import timedelta
                                    last_active_end = event_time + timedelta(seconds=dur)

                                    # Default AFK timeout is 3 minutes (180.0 seconds)
                                    elapsed = (current_time - last_active_end).total_seconds()
                                    if elapsed > 180.0:
                                        is_afk = True
                                        print(f"[{datetime.now()}] Warning: Last active event is stale by {elapsed:.1f}s. Considering user AFK.")
                                except Exception as err:
                                    print(f"Error checking AFK event staledness: {err}")

                # Fetch other custom watcher buckets context for extra details (e.g. Chrome, IDE editors)
                for bid in buckets.keys():
                    if bid.startswith("aw-watcher-") and not bid.startswith("aw-watcher-afk") and not bid.startswith("aw-watcher-window") and not bid.startswith("aw-watcher-vision"):
                        # Get latest event from this custom bucket
                        b_resp = requests.get(
                            f"http://localhost:5600/api/0/buckets/{bid}/events?limit=1",
                            timeout=1.0,
                        )
                        if b_resp.status_code == 200:
                            events = b_resp.json()
                            if events:
                                bucket_context[bid] = events[0].get("data", {})

        except Exception as e:
            print(f"Warning: Could not connect to aw-server to gather context ({e})")

        return window_title, app_name, is_afk, bucket_context

    def _is_audio_active(self) -> bool:
        """Check if any audio stream (playback or capture) is actively running under PipeWire."""
        try:
            res = subprocess.run(
                ["wpctl", "status"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode != 0:
                return False

            lines = res.stdout.splitlines()
            audio_section = False
            streams_section = False

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue

                # Top-level sections in wpctl status are not indented
                if not line.startswith(" ") and not line.startswith("└─") and not line.startswith("├─"):
                    if stripped == "Audio":
                        audio_section = True
                    else:
                        audio_section = False
                    streams_section = False
                    continue

                if audio_section:
                    if "Streams:" in stripped:
                        streams_section = True
                        continue
                    if streams_section and "[active]" in stripped:
                        return True
        except Exception as e:
            print(f"Error checking audio stream status: {e}")
        return False

    def capture_cycle(self):
        """Main screenshot and context capture iteration."""
        # 1. Gather context first to check if the user is active
        window_title, app_name, is_afk, bucket_context = self.fetch_active_window_and_afk()

        # Check if in a call or watching a video to bypass AFK suspension
        title_lower = window_title.lower()
        app_lower = app_name.lower()
        call_video_keywords = [
            "meet.google.com", "teams.microsoft.com", "zoom", "webex", "skype",
            "discord", "slack", "youtube", "netflix", "vlc", "mpv", "plex",
            "twitch", "disney+", "prime video", "hbo", "spotify", "soundcloud",
            "call", "meeting", "video", "conference", "webinar", "stream",
        ]
        has_keyword_match = any(kw in title_lower or kw in app_lower for kw in call_video_keywords)
        audio_active = self._is_audio_active()

        if is_afk and (has_keyword_match or audio_active):
            print(f"[{datetime.now()}] User is AFK, but active call/video detected (Audio active: {audio_active}, Metadata match: {has_keyword_match}). Bypassing AFK sleep.")
            is_afk = False

        if is_afk:
            print(f"[{datetime.now()}] User is AFK. Skipping screenshot capture cycle. Triggering bulk processing.")
            # Trigger asynchronous processing of all pending screenshots
            try:
                from aw_vision.processor import processor
                if processor.is_system_idle():
                    processor.force_process_all()
                else:
                    print(f"[{datetime.now()}] System resources busy. Skipping automatic bulk processing during AFK.")
            except Exception as e:
                print(f"Error auto-triggering bulk processing on AFK: {e}")
            return

        timestamp = time.time()
        file_id = str(uuid.uuid4())

        # Save raw metadata as JSON alongside the raw image
        filename = f"{int(timestamp)}_{file_id}.png"
        raw_image_path = self.raw_dir / filename
        meta_path = self.raw_dir / f"{int(timestamp)}_{file_id}.json"

        # 2. Capture screen based on configured capture mode
        mode = config.capture_mode
        if mode == "both":
            # Capture fullscreen as context archive
            full_filename = f"{int(timestamp)}_{file_id}_full.png"
            full_path = self.raw_dir / full_filename
            self._capture_screenshot_wayland(full_path, mode="fullscreen")

            # Capture active window as primary (used for UI and OCR)
            success = self._capture_screenshot_wayland(raw_image_path, mode="active")
        else:
            success = self._capture_screenshot_wayland(raw_image_path, mode=mode)

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
            "aw_bucket_context": bucket_context,
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
