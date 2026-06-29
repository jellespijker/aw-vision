"""Gemini text and multimodal embedding generation."""
import base64
import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from aw_vision.settings import settings_store


from aw_vision.gemini.http import gemini_request_with_retry, _get_resolved_llm_model


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
