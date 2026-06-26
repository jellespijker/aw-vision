"""Gemini cloud integration package.

Re-exports the public API so existing ``from aw_vision.gemini import <fn>`` imports keep
working after the module was decomposed into focused submodules.
"""
from aw_vision.gemini.http import (
    is_internet_online,
    gemini_request_with_retry,
    _get_resolved_llm_model,
    _enforce_rate_limit,
)
from aw_vision.gemini.embeddings import (
    generate_gemini_embedding,
    generate_gemini_batch_embeddings,
)
from aw_vision.gemini.vision import (
    query_gemini_models,
    run_gemini_ocr,
    run_gemini_combined_ocr_vision,
)
from aw_vision.gemini.chat import run_gemini_chat_agent

__all__ = [
    "is_internet_online",
    "gemini_request_with_retry",
    "_get_resolved_llm_model",
    "_enforce_rate_limit",
    "generate_gemini_embedding",
    "generate_gemini_batch_embeddings",
    "query_gemini_models",
    "run_gemini_ocr",
    "run_gemini_combined_ocr_vision",
    "run_gemini_chat_agent",
]
