"""Vision database package.

Re-exports the ``VisionDB`` class and the shared ``db`` singleton so existing
``from aw_vision.db import db`` imports keep working after decomposition.
"""
from aw_vision.db.core import VisionDB

db = VisionDB()

__all__ = ["VisionDB", "db"]
