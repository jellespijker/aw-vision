"""Gemini model listing and multimodal OCR / vision analysis calls."""

import base64
import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from aw_vision.gemini.http import _get_resolved_llm_model, gemini_request_with_retry
from aw_vision.prompts import build_mcp_context_block, build_user_context_block, prompt_store, render_prompt
from aw_vision.settings import settings_store
from aw_vision.skills import skills_context_for_slot


def query_gemini_models(api_key: Optional[str] = None) -> List[Dict[str, str]]:
    """List available generative models from the Gemini API."""
    key = api_key or settings_store.get("gemini_api_key")
    if not key:
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    try:
        resp = gemini_request_with_retry("GET", url, timeout=10.0)
        data = resp.json()
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            # Clean name from "models/" prefix
            short_name = name.split("/")[-1] if "/" in name else name

            # Filter only generateContent supporting models for LLM dropdown
            supported_methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in supported_methods:
                models.append(
                    {
                        "id": short_name,
                        "display_name": m.get("displayName", short_name),
                        "description": m.get("description", ""),
                    }
                )
        return models
    except Exception as e:
        print(f"Error listing Gemini models: {e}")
        return []


def run_gemini_ocr(img_path: Path, api_key: Optional[str] = None) -> str:
    """Call Gemini to extract raw OCR text from a desktop screenshot."""
    key = api_key or settings_store.get("gemini_api_key")
    model = settings_store.get("gemini_llm_model")
    model = _get_resolved_llm_model(model)
    if not key:
        raise ValueError("Gemini API key is not configured.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    with open(img_path, "rb") as image_file:
        img_b64 = base64.b64encode(image_file.read()).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {"inlineData": {"mimeType": "image/png", "data": img_b64}},
                    {"text": prompt_store.get("gemini_ocr")},
                ]
            }
        ]
    }
    resp = gemini_request_with_retry("POST", url, json_data=payload, timeout=30.0)
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("No generation candidates returned by Gemini.")
    return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()


def run_gemini_combined_ocr_vision(
    img_path: Path,
    full_img_path: Optional[Path],
    projects: List[Dict[str, Any]],
    existing_tags: List[str],
    ocr_text: Optional[str] = None,
    extra_context: Optional[str] = None,
    user_context: Optional[str] = None,
    app_name: Optional[str] = None,
    window_title: Optional[str] = None,
    history_context: Optional[Dict[str, str]] = None,
    template_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform screenshot OCR and Vision Analysis simultaneously in a single, high-efficiency Gemini multimodal API call."""
    key = settings_store.get("gemini_api_key")
    model = settings_store.get("gemini_llm_model")
    model = _get_resolved_llm_model(model)
    if not key:
        raise ValueError("Gemini API key is not configured.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

    # Load and encode images to base64
    contents_parts = []

    # 1. Encode primary crop image
    with open(img_path, "rb") as image_file:
        primary_b64 = base64.b64encode(image_file.read()).decode("utf-8")
    contents_parts.append({"inlineData": {"mimeType": "image/png", "data": primary_b64}})

    # 2. Encode optional fullscreen image
    if full_img_path and full_img_path.exists():
        with open(full_img_path, "rb") as image_file:
            full_b64 = base64.b64encode(image_file.read()).decode("utf-8")
        contents_parts.append({"inlineData": {"mimeType": "image/png", "data": full_b64}})

    # Compile contextual guides
    projects_str = json.dumps(projects, indent=2, ensure_ascii=False)
    tags_str = ", ".join(existing_tags[:100])

    ocr_instruction = (
        "Extract all readable text, titles, labels, browser URLs, files, or characters shown on the screen exactly as displayed. Put this in 'ocr_text'. Keep it clean and unformatted."
        if not ocr_text
        else f"Pre-extracted local OCR text is provided: {ocr_text}. You can use or slightly augment/correct this text for 'ocr_text' rather than re-extracting everything from scratch."
    )

    history = history_context or {}
    prompt = render_prompt(
        template_override or prompt_store.get("gemini_combined"),
        {
            "app_name": app_name or "Unknown",
            "window_title": window_title or "Unknown",
            "user_context_block": build_user_context_block(user_context),
            "mcp_context_block": build_mcp_context_block(extra_context),
            "skills_block": skills_context_for_slot("gemini_combined"),
            "aw_context": history.get("aw_context", "None"),
            "neighbor_context": history.get("neighbor_context", "- Not available."),
            "similar_snapshots": history.get("similar_snapshots", "[]"),
            "app_frequencies": history.get("app_frequencies", "  * Not available."),
            "ocr_instruction": ocr_instruction,
            "projects": projects_str,
            "existing_tags": tags_str,
        },
    )
    contents_parts.append({"text": prompt})

    payload = {"contents": [{"parts": contents_parts}], "generationConfig": {"responseMimeType": "application/json"}}

    resp = gemini_request_with_retry("POST", url, json_data=payload, timeout=90.0)
    data = resp.json()

    # Parse and extract text from Gemini response structure
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("No generation candidates returned by Gemini.")

    text_output = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
    return json.loads(text_output)
