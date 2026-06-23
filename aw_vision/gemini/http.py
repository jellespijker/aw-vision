"""Low-level Gemini HTTP transport: connectivity checks, rate limiting and retrying requests."""
import base64
import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

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
