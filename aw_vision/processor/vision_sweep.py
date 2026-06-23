"""Phase 2 batch sweep: per-screenshot vision analysis & project classification."""
import json
import time
import traceback
from pathlib import Path

import ollama

from aw_vision.config import config
from aw_vision.db import db


class VisionSweepMixin:
    def _phase2_vision_sweep(self, batch_items, projects, N, failed_ids):
        """Vision analysis sweep: 2-pass local pipeline or combined Gemini call per item."""
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
