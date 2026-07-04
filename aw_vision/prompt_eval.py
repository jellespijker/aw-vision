"""Background evaluation of candidate classification templates.

Human-verified project labels are a free evaluation set. This module reruns
the classification stage on a sample of labeled snapshots (whose images still
exist on disk) using a CANDIDATE template — without persisting anything — and
reports per-record agreement with the human label. It turns prompt editing in
Settings → Prompts from guesswork into a measurable change.
"""

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from aw_vision.config import config
from aw_vision.processor.history_context import build_history_context
from aw_vision.prompts import build_user_context_block, prompt_store, render_prompt
from aw_vision.skills import skills_context_for_slot

# Only the prompts that decide project_number can be scored against labels.
EVALUABLE_PROMPT_IDS = ("gemini_combined", "local_synthesis")


def _dedupe_self(history: Dict[str, str], rec_id: str) -> Dict[str, str]:
    """Remove the evaluated record from the similar-snapshots block (label leakage)."""
    try:
        similar = json.loads(history.get("similar_snapshots") or "[]")
        history["similar_snapshots"] = json.dumps([s for s in similar if s.get("id") != rec_id], ensure_ascii=False)
    except Exception:
        pass
    return history


class PromptEvaluator:
    def __init__(self):
        self._lock = threading.Lock()
        self.status: Dict[str, Any] = self._idle_status()

    @staticmethod
    def _idle_status() -> Dict[str, Any]:
        return {
            "is_running": False,
            "prompt_id": None,
            "total": 0,
            "completed": 0,
            "results": [],
            "accuracy": None,
            "error": None,
            "started_at": None,
        }

    # -- public API ----------------------------------------------------------
    def start(self, prompt_id: str, template: str, sample_size: int = 5) -> Dict[str, Any]:
        if prompt_id not in EVALUABLE_PROMPT_IDS:
            raise ValueError(f"Prompt '{prompt_id}' does not classify projects and cannot be evaluated.")
        with self._lock:
            if self.status["is_running"]:
                raise RuntimeError("A prompt evaluation is already running.")
            records = self._pick_records(max(1, min(sample_size, 20)))
            if not records:
                raise ValueError(
                    "No human-verified snapshots with images on disk are available. "
                    "Verify some project labels first."
                )
            self.status = {
                **self._idle_status(),
                "is_running": True,
                "prompt_id": prompt_id,
                "total": len(records),
                "started_at": time.time(),
            }
        threading.Thread(target=self._run, args=(prompt_id, template, records), daemon=True).start()
        return dict(self.status)

    # -- internals -----------------------------------------------------------
    @staticmethod
    def _pick_records(sample_size: int) -> List[dict]:
        from aw_vision.db import db

        candidates = db.query_metadata("human_labeled = true", limit=500)
        picked = []
        for r in candidates:  # newest first
            image_path = r.get("image_path")
            if image_path and Path(image_path).exists():
                picked.append(r)
            if len(picked) >= sample_size:
                break
        return picked

    def _run(self, prompt_id: str, template: str, records: List[dict]):
        matches = 0
        try:
            for rec in records:
                row = {
                    "id": rec.get("id"),
                    "window_title": rec.get("window_title"),
                    "app_name": rec.get("app_name"),
                    "human_project": rec.get("project_number"),
                    "predicted_project": None,
                    "match_type": None,
                    "match": False,
                    "error": None,
                }
                try:
                    predicted = self._classify(prompt_id, template, rec)
                    row["predicted_project"] = predicted.get("project_number")
                    row["match_type"] = predicted.get("match_type")
                    human = (rec.get("project_number") or "None").strip()
                    pred = (row["predicted_project"] or "None").strip()
                    row["match"] = human == pred
                    if row["match"]:
                        matches += 1
                except Exception as e:
                    row["error"] = str(e)[:300]
                with self._lock:
                    self.status["results"].append(row)
                    self.status["completed"] += 1
                    scored = [r for r in self.status["results"] if not r["error"]]
                    self.status["accuracy"] = (matches / len(scored)) if scored else None
        except Exception as e:
            with self._lock:
                self.status["error"] = str(e)
        finally:
            with self._lock:
                self.status["is_running"] = False

    def _classify(self, prompt_id: str, template: str, rec: dict) -> Dict[str, Optional[str]]:
        meta = {
            "app_name": rec.get("app_name"),
            "window_title": rec.get("window_title"),
            "timestamp": rec.get("timestamp"),
            "ocr_text": rec.get("ocr_text"),
            "user_context": rec.get("user_context"),
        }
        img_path = Path(rec.get("image_path"))
        full_img_path = img_path.parent / f"{img_path.stem}_full.png"
        history = _dedupe_self(build_history_context(meta), rec.get("id"))
        projects = config.load_projects()

        if prompt_id == "gemini_combined":
            from aw_vision.gemini import run_gemini_combined_ocr_vision

            res = run_gemini_combined_ocr_vision(
                img_path=img_path,
                full_img_path=full_img_path if full_img_path.exists() else None,
                projects=projects,
                existing_tags=[],
                ocr_text=rec.get("ocr_text") or None,
                user_context=rec.get("user_context") or None,
                app_name=rec.get("app_name"),
                window_title=rec.get("window_title"),
                history_context=history,
                template_override=template,
            )
            return {"project_number": res.get("project_number"), "match_type": res.get("match_type")}

        return self._classify_local(template, rec, meta, img_path, full_img_path, history, projects)

    @staticmethod
    def _classify_local(template, rec, meta, img_path, full_img_path, history, projects):
        """Local two-pass classification mirroring the pipeline, with a candidate synthesis template."""
        import ollama

        from aw_vision.settings import settings_store

        client = ollama.Client(host=config.ollama_host)
        num_ctx = settings_store.get_int("ollama_context_size") or 8192
        images = [str(img_path)]
        if full_img_path.exists():
            images.append(str(full_img_path))

        prompt_v = render_prompt(
            prompt_store.get("local_vision"),
            {
                "image_layout_note": (
                    "The FIRST image is the focused foreground window; the SECOND is the full background desktop context."
                    if len(images) > 1
                    else "The image is the focused foreground window."
                ),
                "app_name": rec.get("app_name") or "Unknown",
                "window_title": rec.get("window_title") or "Unknown",
                "previous_snapshot_block": history.get("previous_snapshot_block", ""),
                "user_context_block": build_user_context_block(rec.get("user_context")),
                "mcp_context_block": "",
                "skills_block": skills_context_for_slot("local_vision"),
            },
        )
        resp_v = client.chat(
            model=config.vision_model,
            messages=[{"role": "user", "content": prompt_v, "images": images}],
            format="json",
            options={"temperature": 0.2, "num_ctx": num_ctx},
            keep_alive=300,
        )
        parsed_v = json.loads(resp_v.get("message", {}).get("content", "") or "{}")

        prompt_syn = render_prompt(
            template,
            {
                "user_context_block": build_user_context_block(rec.get("user_context")),
                "app_name": rec.get("app_name") or "Unknown",
                "window_title": rec.get("window_title") or "Unknown",
                "active_window_description": parsed_v.get("active_window_description") or "",
                "full_desktop_description": parsed_v.get("full_desktop_description") or "",
                "unique_things": parsed_v.get("unique_things") or "",
                "ocr_text": (rec.get("ocr_text") or "")[:1200],
                "external_events": history.get("external_events", ""),
                "aw_context": history.get("aw_context", "None"),
                "neighbor_context": history.get("neighbor_context", "- Not available."),
                "similar_snapshots": history.get("similar_snapshots", "[]"),
                "app_frequencies": history.get("app_frequencies", "  * Not available."),
                "mcp_context_block": "",
                "skills_block": skills_context_for_slot("local_synthesis"),
                "tools_block": "",
                "projects": json.dumps(projects, indent=2, ensure_ascii=False),
                "existing_tags": "[]",
            },
        )
        resp_s = client.chat(
            model=config.vision_model,
            messages=[{"role": "user", "content": prompt_syn}],
            format="json",
            options={"temperature": 0.2, "num_ctx": num_ctx},
            keep_alive=300,
        )
        parsed_s = json.loads(resp_s.get("message", {}).get("content", "") or "{}")
        return {"project_number": parsed_s.get("project_number"), "match_type": parsed_s.get("match_type")}


prompt_evaluator = PromptEvaluator()
