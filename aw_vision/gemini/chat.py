"""Gemini conversational chat agent call for the Memory Agent."""
import base64
import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from aw_vision.settings import settings_store


from aw_vision.gemini.http import gemini_request_with_retry, _get_resolved_llm_model


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
