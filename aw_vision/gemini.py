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


def _get_resolved_llm_model(model_name: str) -> str:
    """Map deprecated/preview Gemini LLM models to currently supported production versions."""
    if model_name in (
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-lite-preview",
        "gemini-2.0-flash-lite-preview-02-05",
        "gemini-2.0-flash-lite-001",
        "gemini-2.0-flash",
        "gemini-2.0-flash-preview",
        "gemini-2.0-flash-001",
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
        "gemma-4-26b-a4b-it",
        "gemma-4-31b-it",
    ):
        print(f"[Gemini Model Resolver] Resolving model '{model_name}' to 'gemini-2.5-flash' for cloud processing.")
        return "gemini-2.5-flash"
    return model_name


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
                if attempt == max_retries:
                    try:
                        err_data = resp.json()
                        err_msg = err_data.get("error", {}).get("message", resp.text)
                    except Exception:
                        err_msg = resp.text
                    raise RuntimeError(f"Gemini API 429 RESOURCE_EXHAUSTED: {err_msg}")

                print(
                    f"[Gemini API 429] Too Many Requests. Response: {resp.text}. Retrying in {backoff:.1f}s (attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(backoff)
                backoff *= 2.0
                continue

            resp.raise_for_status()
            return resp

        except requests.exceptions.RequestException as e:
            # Check for non-retryable HTTP client errors (4xx other than 429) to fail fast
            if hasattr(e, "response") and e.response is not None:
                status_code = e.response.status_code
                if 400 <= status_code < 500 and status_code != 429:
                    try:
                        err_data = e.response.json()
                        err_msg = err_data.get("error", {}).get("message", str(e))
                        raise RuntimeError(f"Gemini API Client Error ({status_code}): {err_msg}")
                    except Exception:
                        raise RuntimeError(f"Gemini API Client Error ({status_code}): {e}")

            if attempt == max_retries:
                # Attempt to extract detailed API message if available
                if hasattr(e, "response") and e.response is not None:
                    try:
                        err_data = e.response.json()
                        err_msg = err_data.get("error", {}).get("message", str(e))
                        raise RuntimeError(f"Gemini API Error: {err_msg}")
                    except Exception:
                        pass
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


def generate_gemini_embedding(text: str, img_path: Optional[str] = None, api_key: Optional[str] = None) -> List[float]:
    """Generate a single text (+ optional image) embedding using the configured Gemini embedding model."""
    key = api_key or settings_store.get("gemini_api_key")
    model = settings_store.get("gemini_embedding_model")
    if model in ("gemini-embeddings-002", "gemini-embedding-002", "gemini-embbeding-002"):
        model = "gemini-embedding-2"
    if not key:
        raise ValueError("Gemini API key is missing. Please configure it in Settings.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={key}"

    parts = [{"text": text}]
    if img_path:
        p = Path(img_path)
        if p.exists():
            try:
                with open(p, "rb") as image_file:
                    img_b64 = base64.b64encode(image_file.read()).decode("utf-8")
                parts.append({
                    "inlineData": {
                        "mimeType": "image/png",
                        "data": img_b64
                    }
                })
            except Exception as ex:
                print(f"Error reading image '{img_path}' for single embedding: {ex}")

    payload = {"content": {"parts": parts}}
    try:
        resp = gemini_request_with_retry("POST", url, json_data=payload, timeout=15.0)
        data = resp.json()

        # Validate that we actually got embedding values back
        values = data.get("embedding", {}).get("values", [])
        if not values:
            if "error" in data:
                err_msg = data["error"].get("message", "Unknown error")
                raise RuntimeError(f"Gemini API returned error: {err_msg}")
            raise RuntimeError("Gemini API returned empty embedding values.")

        return values
    except Exception as e:
        print(f"Error generating Gemini embedding for model '{model}': {e}")
        raise e


def generate_gemini_batch_embeddings(
    texts: List[str], img_paths: Optional[List[Optional[str]]] = None, api_key: Optional[str] = None
) -> List[List[float]]:
    """Generate a batch of text (+ optional image) embeddings in a single request using the Gemini API."""
    key = api_key or settings_store.get("gemini_api_key")
    model = settings_store.get("gemini_embedding_model")
    if model in ("gemini-embeddings-002", "gemini-embedding-002", "gemini-embbeding-002"):
        model = "gemini-embedding-2"
    if not key:
        raise ValueError("Gemini API key is missing. Please configure it in Settings.")
    if not texts:
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents?key={key}"
    requests_payload = []
    for i, t in enumerate(texts):
        parts = [{"text": t}]
        if img_paths and i < len(img_paths) and img_paths[i]:
            p = Path(img_paths[i])
            if p.exists():
                try:
                    with open(p, "rb") as image_file:
                        img_b64 = base64.b64encode(image_file.read()).decode("utf-8")
                    parts.append({
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": img_b64
                        }
                    })
                except Exception as ex:
                    print(f"Error reading image '{img_paths[i]}' for batch embedding: {ex}")

        requests_payload.append({"model": f"models/{model}", "content": {"parts": parts}})

    payload = {"requests": requests_payload}

    try:
        resp = gemini_request_with_retry("POST", url, json_data=payload, timeout=60.0)
        data = resp.json()

        # Check for error field inside a 200 response body
        if "error" in data:
            err_msg = data["error"].get("message", "Unknown error")
            raise RuntimeError(f"Gemini API returned error: {err_msg}")

        embeddings = []
        for emb in data.get("embeddings", []):
            embeddings.append(emb.get("values", []))

        # Ensure we actually received embeddings back and that the count matches
        if not embeddings and len(texts) > 0:
            raise RuntimeError("Gemini API returned an empty embeddings list for batch request.")

        if len(embeddings) != len(texts):
            raise RuntimeError(f"Gemini API returned {len(embeddings)} embeddings for {len(texts)} requests.")

        return embeddings
    except Exception as e:
        print(f"Error in Gemini batch embedding call: {e}")
        raise e


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
        "1. OCR: Extract all readable text, titles, labels, browser URLs, files, or characters shown on the screen exactly as displayed. Put this in 'ocr_text'. Keep it clean and unformatted."
        if not ocr_text
        else f"1. OCR: Pre-extracted local OCR text is provided: {ocr_text}. You can use or slightly augment/correct this text for 'ocr_text' rather than re-extracting everything from scratch."
    )

    prompt = f"""
Analyze this desktop screenshot (the first image is the focused foreground crop; the second is the full background desktop context, if provided).

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


def run_gemini_chat_agent(prompt: str, history: List[Dict[str, str]], context_size: int = 1048576) -> str:
    """Run an interactive conversation stream using Gemini LLM for the Memory Agent."""
    key = settings_store.get("gemini_api_key")
    model = settings_store.get("agent_model")
    model = _get_resolved_llm_model(model)
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
