"""Mirror processed screenshot metadata back into an aw-server vision bucket."""
import time

import requests

from aw_vision.config import config


class MirrorMixin:
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
