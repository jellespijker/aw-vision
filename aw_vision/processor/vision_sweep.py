"""Phase 2 batch sweep: per-screenshot vision analysis & project classification."""

import json
import time
import traceback
from pathlib import Path

import ollama

from aw_vision.config import config
from aw_vision.db import db
from aw_vision.processor.history_context import build_history_context
from aw_vision.prompts import build_mcp_context_block, build_user_context_block, prompt_store, render_prompt
from aw_vision.skills import skills_context_for_slot


def _normalize_match_type(value) -> str | None:
    """Validate the model's match_type output to one of direct/thematic/none."""
    v = (str(value or "")).strip().lower()
    return v if v in ("direct", "thematic", "none") else None


def mcp_enrich(slot: str, query: str) -> str:
    """Fetch external MCP context assigned to a given pipeline prompt slot.

    Returns an empty string when no MCP server is assigned to ``slot`` (the common
    case), guaranteeing zero behavioural or performance impact unless the user has
    explicitly wired an MCP server into that prompt. Never raises.
    """
    try:
        from aw_vision.mcp_manager import mcp_manager

        if not mcp_manager.servers_for_slot(slot):
            return ""
        return mcp_manager.gather_context_for_slot(slot, query)
    except Exception as e:
        print(f"[MCP] Pipeline enrichment failed for slot '{slot}': {e}")
        return ""


class VisionSweepMixin:
    def _phase2_vision_sweep(self, batch_items, projects, N, failed_ids):
        """Vision analysis sweep: 2-pass local pipeline or combined Gemini call per item."""
        for idx, (img_path, meta_path, rec_id, meta) in enumerate(batch_items):
            with self.lock:
                self.current_rec_id = rec_id
                self.current_stage = f"Phase 2/3 (Vision Analysis): Item {self.current_batch_processed + idx + 1}/{self.current_batch_total}"
            try:
                vision_start = time.time()
                self.log_step(
                    rec_id, f"Phase 2/3: Vision model analysis & Project classification (item {idx + 1}/{N} in batch)"
                )

                # Only run Vision if not already processed (meaning we don't have description)
                if "description" not in meta or meta["description"] is None:
                    full_img_filename = f"{img_path.stem}_full.png"
                    full_img_path = img_path.parent / full_img_filename

                    from aw_vision.gemini import is_internet_online, run_gemini_combined_ocr_vision
                    from aw_vision.settings import settings_store

                    use_gemini = settings_store.get("provider") == "gemini" and is_internet_online()

                    if use_gemini:
                        cached_ocr = meta.get("ocr_text")
                        if cached_ocr:
                            self.log_step(rec_id, "Running Gemini Vision analysis with pre-extracted OCR text...")
                        else:
                            self.log_step(rec_id, "Running combined Gemini OCR and Vision analysis...")
                        existing_tags = db.get_all_unique_tags()
                        if len(existing_tags) > 100:
                            existing_tags = existing_tags[:100]

                        # Optional external MCP context for the combined cloud prompt.
                        mcp_query = f"{meta.get('app_name', '')} {meta.get('window_title', '')} {(cached_ocr or '')[:200]}".strip()
                        mcp_ctx_combined = mcp_enrich("gemini_combined", mcp_query)
                        if mcp_ctx_combined:
                            self.log_step(rec_id, "Injected external MCP context into Gemini combined prompt.")
                        user_context = (meta.get("user_context") or "").strip()
                        if user_context:
                            self.log_step(rec_id, "Injected user-provided context note into Gemini combined prompt.")
                        try:
                            res = run_gemini_combined_ocr_vision(
                                img_path=img_path,
                                full_img_path=full_img_path if full_img_path.exists() else None,
                                projects=projects,
                                existing_tags=existing_tags,
                                ocr_text=cached_ocr if cached_ocr else None,
                                extra_context=mcp_ctx_combined or None,
                                user_context=user_context or None,
                                app_name=meta.get("app_name"),
                                window_title=meta.get("window_title"),
                                history_context=build_history_context(meta),
                            )
                            meta["ocr_text"] = res.get("ocr_text", "") or cached_ocr or ""
                            meta["description"] = res.get("description", "No description generated.")
                            meta["tags"] = res.get("tags", [])
                            meta["project_number"] = res.get("project_number", "None")
                            meta["unique_things"] = res.get("unique_things", "None detected.")
                            meta["analysis_reasoning"] = (res.get("project_reasoning") or "").strip() or None
                            meta["classification_confidence"] = _normalize_match_type(res.get("match_type"))
                            meta["vector"] = []  # Generated in Phase 3
                            meta["duration_vision"] = time.time() - vision_start

                            # Persist results to metadata JSON file on disk
                            with open(meta_path, "w", encoding="utf-8") as f:
                                json.dump(meta, f, indent=2)

                            self.log_step(
                                rec_id, f"Gemini Combined Analysis complete. Description: {meta['description']}"
                            )
                            continue
                        except Exception as eg:
                            self.log_step(rec_id, f"Error calling Gemini, falling back to local Ollama: {eg}")

                    existing_tags = db.get_all_unique_tags()
                    if len(existing_tags) > 100:
                        existing_tags = existing_tags[:100]

                    projects_str = json.dumps(projects, indent=2, ensure_ascii=False)

                    # Historical/temporal context from previously processed snapshots
                    # (shared with the Gemini combined prompt via history_context).
                    history = build_history_context(meta)

                    raw_ocr = meta.get("ocr_text", "")
                    truncated_ocr = self.summarize_ocr_text(raw_ocr, max_chars=1200)

                    client = ollama.Client(host=config.ollama_host)

                    num_ctx = settings_store.get_int("ollama_context_size") or 8192
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
                    # Optional external MCP context (for reference only) for the vision pass.
                    mcp_ctx_vision = mcp_enrich(
                        "local_vision", f"{meta.get('app_name', '')} {meta.get('window_title', '')}".strip()
                    )
                    user_context = (meta.get("user_context") or "").strip()
                    if user_context:
                        self.log_step(rec_id, "Injected user-provided context note into local pipeline prompts.")
                    try:
                        self.log_step(
                            rec_id, "Vision pass 1/2: Analyzing focused window, desktop context & unique artifacts..."
                        )
                        images_v = [str(img_path)]
                        if has_full:
                            images_v.append(str(full_img_path))
                        prompt_v = render_prompt(
                            prompt_store.get("local_vision"),
                            {
                                "image_layout_note": (
                                    "The FIRST image is the focused foreground window; the SECOND is the full background desktop context."
                                    if has_full
                                    else "The image is the focused foreground window."
                                ),
                                "app_name": meta.get("app_name") or "Unknown",
                                "window_title": meta.get("window_title") or "Unknown",
                                "previous_snapshot_block": history.get("previous_snapshot_block", ""),
                                "user_context_block": build_user_context_block(user_context),
                                "mcp_context_block": build_mcp_context_block(mcp_ctx_vision),
                                "skills_block": skills_context_for_slot("local_vision"),
                            },
                        )
                        response_v = client.chat(
                            model=config.vision_model,
                            messages=[{"role": "user", "content": prompt_v, "images": images_v}],
                            format="json",
                            options={"temperature": 0.2, "num_ctx": num_ctx},
                            keep_alive=stage_keep_alive,
                        )
                        parsed_v = json.loads(response_v.get("message", {}).get("content", "") or "{}")
                        active_window_description = (
                            parsed_v.get("active_window_description") or ""
                        ).strip() or active_window_description
                        full_desktop_description = (
                            parsed_v.get("full_desktop_description") or ""
                        ).strip() or full_desktop_description
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
                    analysis_reasoning = None
                    classification_confidence = None
                    try:
                        self.log_step(
                            rec_id,
                            "Vision pass 2/2: Classifying project, generating tags & synthesizing description...",
                        )

                        # MCP tools assigned to this slot are exposed as callable ReAct
                        # tools (uniform CALL_TOOL protocol) instead of the old
                        # pre-gathered context heuristic. With no tools assigned this
                        # is exactly one JSON-constrained call, as before.
                        from aw_vision.tooling import (
                            extract_json_object,
                            format_tools_block,
                            mcp_tools_for_slot,
                            run_react_loop,
                        )

                        syn_tools = mcp_tools_for_slot("local_synthesis")
                        if syn_tools:
                            self.log_step(
                                rec_id,
                                f"Synthesis runs as ReAct agent with {len(syn_tools)} MCP tool(s): "
                                + ", ".join(t.name for t in syn_tools),
                            )

                        prompt_syn = render_prompt(
                            prompt_store.get("local_synthesis"),
                            {
                                "user_context_block": build_user_context_block(user_context),
                                "app_name": meta.get("app_name") or "Unknown",
                                "window_title": meta.get("window_title") or "Unknown",
                                "active_window_description": active_window_description,
                                "full_desktop_description": full_desktop_description,
                                "unique_things": unique_things,
                                "ocr_text": truncated_ocr,
                                "aw_context": history.get("aw_context", "None"),
                                "neighbor_context": history.get("neighbor_context", "- Not available."),
                                "similar_snapshots": history.get("similar_snapshots", "[]"),
                                "app_frequencies": history.get("app_frequencies", "  * Not available."),
                                "mcp_context_block": "",
                                "skills_block": skills_context_for_slot("local_synthesis"),
                                "tools_block": format_tools_block(syn_tools),
                                "projects": projects_str,
                                "existing_tags": existing_tags,
                            },
                        )

                        def _syn_llm(loop_messages, force_json):
                            # Tool turns keep the model warm; only a tool-less run may
                            # unload immediately on the last batch item.
                            response = client.chat(
                                model=config.vision_model,
                                messages=loop_messages,
                                format="json" if (force_json or not syn_tools) else None,
                                options={"temperature": 0.2, "num_ctx": num_ctx},
                                keep_alive=final_keep_alive if not syn_tools else 300,
                            )
                            return response.get("message", {}).get("content", "") or ""

                        reply_syn, syn_events = run_react_loop(
                            _syn_llm,
                            prompt_syn,
                            syn_tools,
                            max_steps=2,
                            log=lambda m: self.log_step(rec_id, m),
                        )
                        for ev in syn_events:
                            self.log_step(
                                rec_id,
                                f"Tool {ev['tool']}({str(ev['args'])[:80]}) -> "
                                f"{'ERROR: ' if ev['error'] else ''}{ev['result_preview'][:160]}",
                            )
                        parsed_syn = json.loads(extract_json_object(reply_syn))
                        project_number = (parsed_syn.get("project_number") or "None").strip() or "None"
                        syn_tags = parsed_syn.get("tags", [])
                        tags = syn_tags if isinstance(syn_tags, list) else []
                        description = (parsed_syn.get("description") or "").strip() or description
                        analysis_reasoning = (parsed_syn.get("project_reasoning") or "").strip() or None
                        classification_confidence = _normalize_match_type(parsed_syn.get("match_type"))
                        self.log_step(
                            rec_id,
                            f"Synthesis complete: Project='{project_number}', Tags={tags}, Desc={description[:120]}...",
                        )
                        if analysis_reasoning:
                            self.log_step(rec_id, f"Classification reasoning: {analysis_reasoning[:300]}")
                    except Exception as esyn:
                        self.log_step(rec_id, f"Warning: Synthesis pass failed: {esyn}")

                    # Assign results to meta dictionary
                    meta["description"] = description
                    meta["tags"] = tags
                    meta["project_number"] = project_number
                    meta["unique_things"] = unique_things
                    meta["analysis_reasoning"] = analysis_reasoning
                    meta["classification_confidence"] = classification_confidence
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
