"""Gemini model listing and multimodal OCR / vision analysis calls."""

import base64
import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from aw_vision.gemini.http import _get_resolved_llm_model, gemini_request_with_retry
from aw_vision.settings import settings_store


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
                    {
                        "text": "Extract all readable text, titles, labels, browser URLs, files, or characters shown on this desktop screenshot exactly as shown. Do not explain, describe, or add any meta-commentary. Just output the extracted text."
                    },
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

    mcp_context_block = ""
    if extra_context:
        mcp_context_block = (
            "\nExternal MCP Tool Context (authoritative supplementary data from connected "
            f"integrations such as GitHub/Jira; use it to improve project classification and tags):\n{extra_context}\n"
        )

    ocr_instruction = (
        "1. OCR: Extract all readable text, titles, labels, browser URLs, files, or characters shown on the screen exactly as displayed. Put this in 'ocr_text'. Keep it clean and unformatted."
        if not ocr_text
        else f"1. OCR: Pre-extracted local OCR text is provided: {ocr_text}. You can use or slightly augment/correct this text for 'ocr_text' rather than re-extracting everything from scratch."
    )

    prompt = f"""
Analyze this desktop screenshot (the first image is the focused foreground crop; the second is the full background desktop context, if provided).
{mcp_context_block}
Perform the following analytical indexing tasks:
{ocr_instruction}
2. Foreground Context: Describe precisely what application, document, URL, code, or workspace section is open, focusing on the focused crop. Be objective and fine-grained. Put this in 'active_window_description'.
3. Peripheral Context: Describe peripheral, background, or accessory windows visible outside the focused area. Put this in 'full_desktop_description'.
4. Project Classification: Map this activity to one of the active work projects from this guide:
{projects_str}
CRITICAL RULE: If there is no strong, direct, explicit link between screen contents and a project's guidelines, return "None". Be conservative. Put this in 'project_number'.
5. Technical Tags: Generate 3 to 7 highly relevant, technical tags. Prioritize matching these existing database tags: [{tags_str}]. Put this in 'tags'.
6. Synthesis (Caveman-Style): Synthesize everything into an ultra-dense, technical "Caveman-style" summary. Speak in fragments, use semicolons, and omit filler words (the, a, is, was, were, to, of, for). Put this in 'description'.
   Example: "Dev aw-vision UI. Refactored list component; displaying unique elements via exact CSS tokens."
7. Unique Artifacts: Identify specific terminal commands, active code blocks, file paths, specialized charts, or unique widgets present on the screen. Put this in 'unique_things'.

You must respond in valid JSON format matching this exact schema:
{{
  "ocr_text": "string",
  "active_window_description": "string",
  "full_desktop_description": "string",
  "project_number": "string",
  "tags": ["string"],
  "description": "string",
  "unique_things": "string"
}}
"""
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
