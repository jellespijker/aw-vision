"""Bulk processor package.

Re-exports ``caveman_compress_text``, ``BulkProcessor`` and the ``processor`` singleton so
existing imports keep working after the module was decomposed into focused submodules.
"""
from aw_vision.processor.text import caveman_compress_text
from aw_vision.processor.core import BulkProcessor

processor = BulkProcessor()

__all__ = ["caveman_compress_text", "BulkProcessor", "processor"]
