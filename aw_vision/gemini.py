import base64
import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from aw_vision.settings import settings_store

# Thread-safe rate limiter tracking
_last_request_time = 0.0


def is_internet_online() -> bool:
    """Check if the internet is online and the Gemini API is reachable with a short timeout."""
    try:
        # Check standard google API connectivity
        requests.get("https://generativelanguage.googleapis.com", timeout=2.0)
        return True
    except Exception:
        return False


def _enforce_rate_limit():
    """Enforce a proactive delay between consecutive Gemini API calls to stay under Free Tier RPM limits."""
    global _last_request_time
    delay = settings_store.get_float("gemini_rate_limit_delay")
    if delay <= 0.0:
        return

    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < delay:
        wait_time = delay - elapsed
        print(f"[Gemini Rate Limiter] Spacing requests. Sleeping for {wait_time:.2f} seconds...")
        time.sleep(wait_time)
    _last_request_time = time.time()


def gemini_request_with_retry(
    method: str, url: str, json_data: Optional[Dict[str, Any]] = None, timeout: float = 30.0, max_retries: int = 3
) -> requests.Response:
    """Execute an HTTP request to Gemini API with proactive rate-limiting and reactive exponential backoff for HTTP 429."""
    _enforce_rate_limit()

    backoff = 2.0
    for attempt in range(max_retries + 1):
        try:
            if method.upper() == "POST":
                resp = requests.post(url, json=json_data, timeout=timeout)
            else:
                resp = requests.get(url, timeout=timeout)

            # Check if we hit rate limits (429) or other HTTP errors
            if resp.status_code == 429:
                print(
                    f"[Gemini API 429] Too Many Requests. Retrying in {backoff:.1f}s (attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(backoff)
                backoff *= 2.0
                continue

            resp.raise_for_status()
            return resp

        except requests.exceptions.RequestException as e:
            if attempt == max_retries:
                raise e

            # Handle generic connection issues or timeouts with backoff
            print(f"[Gemini Request Error] {e}. Retrying in {backoff:.1f}s (attempt {attempt + 1}/{max_retries})...")
            time.sleep(backoff)
            backoff *= 2.0

    raise RuntimeError("Gemini API call failed after multiple retries.")


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


def generate_gemini_embedding(text: str, api_key: Optional[str] = None) -> List[float]:
    """Generate a single text embedding using the configured Gemini embedding model."""
    key = api_key or settings_store.get("gemini_api_key")
    model = settings_store.get("gemini_embedding_model")
    if model == "gemini-embeddings-002":
        model = "gemini-embedding-2"
    if not key:
        print("Gemini API key is missing. Skipping embedding.")
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={key}"
    payload = {"content": {"parts": [{"text": text}]}}
    try:
        resp = gemini_request_with_retry("POST", url, json_data=payload, timeout=15.0)
        data = resp.json()
        return data.get("embedding", {}).get("values", [])
    except Exception as e:
        print(f"Error generating Gemini embedding for model '{model}': {e}")
        return []


def generate_gemini_batch_embeddings(texts: List[str], api_key: Optional[str] = None) -> List[List[float]]:
    """Generate a batch of text embeddings in a single request using the Gemini API."""
    key = api_key or settings_store.get("gemini_api_key")
    model = settings_store.get("gemini_embedding_model")
    if model == "gemini-embeddings-002":
        model = "gemini-embedding-2"
    if not key or not texts:
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents?key={key}"
    requests_payload = []
    for t in texts:
        requests_payload.append({"model": f"models/{model}", "content": {"parts": [{"text": t}]}})
    payload = {"requests": requests_payload}

    try:
        resp = gemini_request_with_retry("POST", url, json_data=payload, timeout=60.0)
        data = resp.json()
        embeddings = []
        for emb in data.get("embeddings", []):
            embeddings.append(emb.get("values", []))
        return embeddings
    except Exception as e:
        print(f"Error in Gemini batch embedding call: {e}")
        return []


def run_gemini_combined_ocr_vision(
    img_path: Path, full_img_path: Optional[Path], projects: List[Dict[str, Any]], existing_tags: List[str]
) -> Dict[str, Any]:
    """Perform screenshot OCR and Vision Analysis simultaneously in a single, high-efficiency Gemini multimodal API call."""
    key = settings_store.get("gemini_api_key")
    model = settings_store.get("gemini_llm_model")
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

    prompt = f"""
Analyze this desktop screenshot (the first image is the focused foreground crop; the second is the full background desktop context, if provided).

Perform the following analytical indexing tasks:
1. OCR: Extract all readable text, titles, labels, browser URLs, files, or characters shown on the screen exactly as displayed. Put this in 'ocr_text'. Keep it clean and unformatted.
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

    resp = gemini_request_with_retry("POST", url, json_data=payload, timeout=45.0)
    data = resp.json()

    # Parse and extract text from Gemini response structure
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("No generation candidates returned by Gemini.")

    text_output = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
    return json.loads(text_output)


def run_gemini_chat_agent(prompt: str, history: List[Dict[str, str]], context_size: int = 1048576) -> str:
    """Run an interactive conversation stream using Gemini LLM for the Memory Agent."""
    key = settings_store.get("gemini_api_key")
    model = settings_store.get("agent_model")
    if not key:
        return "Gemini API key is not configured for the Agent."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

    # Map conversation history into Gemini format
    contents = []
    for h in history:
        role = h.get("role")
        content = h.get("content", "")
        # Gemini roles must be 'user' or 'model'
        gemini_role = "user" if role == "user" else "model"
        contents.append({"role": gemini_role, "parts": [{"text": content}]})

    # Append current prompt
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    # Setup safety settings or token limits if needed based on configurable context size
    payload = {"contents": contents, "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.2}}

    try:
        resp = gemini_request_with_retry("POST", url, json_data=payload, timeout=60.0)
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return "Error: No candidates returned by Gemini chat agent."
        return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
    except Exception as e:
        traceback.print_exc()
        return f"Error contacting Gemini chat agent: {e}"
