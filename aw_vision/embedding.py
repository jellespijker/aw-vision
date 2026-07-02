"""Provider-agnostic semantic embedding helpers.

Centralizes the embedding concern that was previously spread across ``db.py``, ``gemini.py`` and
``processor.py``:

* :func:`build_embedding_text` — the right-sized text representation of a screenshot.
* :func:`embedding_model_supports_image` — whether an embedding model can consume images.
* :func:`generate_embedding` — generate a vector via the configured provider (multimodal Gemini
  or local Ollama), padding/truncating to the active database dimension.

Heavy dependencies (settings, gemini client, db) are imported lazily inside the functions to keep
this module free of import cycles.
"""
from typing import Callable, List, Optional

import requests

from aw_vision.config import config


def build_embedding_text(record: dict, max_ocr_chars: int = 1200) -> str:
    """Build a consistent, right-sized text representation of a screenshot for semantic embedding.

    Combines the high-signal structured metadata (app, window, project, tags) with the
    synthesized description and a bounded slice of OCR text. Heavy raw artifacts (full image
    bytes, unbounded OCR) are intentionally excluded so the embedding stays focused and cheap
    while still capturing what the user was actually doing. Used by both live ingestion and the
    database-wide re-embedding migration so document vectors stay consistent.
    """
    app_name = (record.get("app_name") or "").strip()
    window_title = (record.get("window_title") or "").strip()
    description = (record.get("description") or "").strip()
    project = (record.get("project_number") or "").strip()
    tags = record.get("tags") or []
    if isinstance(tags, list):
        tags_str = ", ".join(t.strip() for t in tags if t and str(t).strip())
    else:
        tags_str = str(tags).strip()
    ocr = (record.get("ocr_text") or "").strip()
    if max_ocr_chars and len(ocr) > max_ocr_chars:
        ocr = ocr[:max_ocr_chars]
    user_context = (record.get("user_context") or "").strip()

    lines = []
    if app_name:
        lines.append(f"Application: {app_name}")
    if window_title:
        lines.append(f"Window: {window_title}")
    if project and project.lower() != "none":
        lines.append(f"Project: {project}")
    if tags_str:
        lines.append(f"Tags: {tags_str}")
    if user_context:
        lines.append(f"User Notes: {user_context}")
    lines.append(f"Description: {description}")
    lines.append(f"Extracted Screen Text: {ocr}")
    return "\n".join(lines)


# Gemini embedding models that accept inline image parts (i.e. true multimodal embeddings).
# For these we attach the screenshot so the vector captures visual layout/signal that the
# OCR + description text cannot. Text-only embedding models skip the image to stay cheap.
_MULTIMODAL_EMBEDDING_HINTS = (
    "embedding-2",
    "embeddings-2",
    "embedding-002",
    "embeddings-002",
    "multimodal",
)


def embedding_model_supports_image(model: Optional[str]) -> bool:
    """Return True if the given embedding model id supports multimodal (text + image) inputs."""
    if not model:
        return False
    m = model.lower()
    return any(hint in m for hint in _MULTIMODAL_EMBEDDING_HINTS)


def generate_embedding(
    text: str,
    img_path: Optional[str] = None,
    rec_id: Optional[str] = None,
    keep_alive: int = 300,
    log: Optional[Callable[[str, str], None]] = None,
) -> List[float]:
    """Generate an embedding vector for ``text`` (+ optional image) using the active provider.

    The screenshot at ``img_path`` is only forwarded to multimodal-capable Gemini models; local
    Ollama and text-only models receive text only. The result is padded/truncated to the active
    database vector dimension. ``log`` is an optional ``(rec_id, message)`` callback used for
    per-record progress reporting.
    """
    from aw_vision.settings import settings_store
    from aw_vision.gemini import generate_gemini_embedding, is_internet_online
    from aw_vision.db import db

    def _log(message: str, print_if_no_logger: bool = False):
        if rec_id and log:
            log(rec_id, message)
        elif print_if_no_logger:
            print(message)

    provider = settings_store.get("provider")
    use_gemini = (provider == "gemini" and is_internet_online())

    embedding: List[float] = []
    if use_gemini:
        try:
            emb_model = settings_store.get("gemini_embedding_model")
            # Only attach the screenshot for multimodal-capable embedding models; text-only
            # models would just pay the base64 upload cost for no gain.
            use_img = img_path if (img_path and embedding_model_supports_image(emb_model)) else None
            kind = "multimodal " if use_img else ""
            _log(f"Generating Gemini {kind}semantic embedding using '{emb_model or 'default'}'.")
            embedding = generate_gemini_embedding(text, img_path=use_img)
        except Exception as e:
            _log(f"Error generating Gemini embedding: {e}. Falling back to Ollama.", print_if_no_logger=True)

    if not embedding:
        try:
            model = settings_store.get("ollama_embedding_model") or config.embedding_model
            _log(f"Generating local semantic embedding using '{model}' with keep_alive={keep_alive}s...")
            url = f"{config.ollama_host}/api/embeddings"
            payload = {"model": model, "prompt": text, "keep_alive": keep_alive}
            resp = requests.post(url, json=payload, timeout=30.0)
            if resp.status_code == 200:
                embedding = resp.json().get("embedding", [])
        except Exception as e:
            _log(f"Error generating embedding from Ollama: {e}", print_if_no_logger=True)

    expected_dim = db.get_embedding_dimension()
    if not embedding:
        return [0.0] * expected_dim

    # Pad or truncate to expected dimension
    if len(embedding) < expected_dim:
        _log(f"Correction: Padding generated vector from {len(embedding)} to {expected_dim} to match DB layout.")
        embedding = list(embedding) + [0.0] * (expected_dim - len(embedding))
    elif len(embedding) > expected_dim:
        _log(f"Correction: Truncating generated vector from {len(embedding)} to {expected_dim} to match DB layout.")
        embedding = list(embedding)[:expected_dim]

    return embedding
