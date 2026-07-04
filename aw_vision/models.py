"""Typed snapshot record shared by the DB layer, pipeline and API.

The snapshot's shape was previously re-declared as raw dicts in five places
(schema, phase-3 commit, and three API payload builders), so every new column
meant a multi-file hunt. This model is the single source of truth: rows come
in via :meth:`from_lance` / :meth:`from_pending_meta`, and go out via
:meth:`to_api` (frontend payload) or :meth:`to_lance` (DB commit).
"""

import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Snapshot(BaseModel):
    id: str
    timestamp: float = 0.0
    image_path: Optional[str] = None
    window_title: str = "Unknown"
    app_name: str = "Unknown"
    is_afk: bool = False
    description: Optional[str] = None
    ocr_text: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    project_number: Optional[str] = None
    human_labeled: bool = False
    unique_things: Optional[str] = None
    user_context: Optional[str] = None
    analysis_reasoning: Optional[str] = None
    classification_confidence: Optional[str] = None
    people: List[str] = Field(default_factory=list)
    project_likelihoods: Optional[str] = None  # JSON: {project: probability}, top-k
    duration_ocr: Optional[float] = None
    duration_vision: Optional[float] = None
    duration_embedding: Optional[float] = None
    duration_total: Optional[float] = None

    # -- constructors ---------------------------------------------------------
    @classmethod
    def from_lance(cls, row: Dict[str, Any]) -> "Snapshot":
        """Build from a raw LanceDB row, tolerating missing/extra columns."""
        known = cls.model_fields.keys()
        data = {k: v for k, v in row.items() if k in known and v is not None}
        data.setdefault("id", row.get("id") or "")
        return cls(**data)

    @classmethod
    def from_pending_meta(cls, meta: Dict[str, Any], image_filename: Optional[str] = None) -> "Snapshot":
        """Build from a raw-queue metadata JSON (not yet analyzed)."""
        return cls(
            id=meta.get("id") or "",
            timestamp=float(meta.get("timestamp", 0.0)),
            image_path=image_filename,
            window_title=meta.get("window_title", "Unknown"),
            app_name=meta.get("app_name", "Unknown"),
            is_afk=bool(meta.get("is_afk", False)),
            user_context=meta.get("user_context"),
        )

    # -- serializers ----------------------------------------------------------
    def to_api(
        self, *, is_processed: bool = True, distance: Optional[float] = None, description_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """The frontend HistoryRecord payload (image path reduced to a filename)."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "image_filename": os.path.basename(self.image_path) if self.image_path else None,
            "window_title": self.window_title,
            "app_name": self.app_name,
            "is_afk": self.is_afk,
            "description": description_override if description_override is not None else self.description,
            "ocr_text": self.ocr_text,
            "tags": list(self.tags),
            "project_number": self.project_number,
            "human_labeled": self.human_labeled,
            "is_processed": is_processed,
            "distance": distance,
            "unique_things": self.unique_things,
            "user_context": self.user_context,
            "analysis_reasoning": self.analysis_reasoning,
            "classification_confidence": self.classification_confidence,
            "people": list(self.people),
            "project_likelihoods": self.project_likelihoods,
        }

    def to_lance(self, vector: List[float]) -> Dict[str, Any]:
        """The LanceDB record for commit (project 'None' normalized to null)."""
        record = self.model_dump()
        if record.get("project_number") == "None":
            record["project_number"] = None
        record["vector"] = vector
        return record


class ExternalEvent(BaseModel):
    """A neutral external-context event (calendar/mail/chat/vcs), provider-agnostic.

    Collectors adapt Google, Microsoft, git or any other provider into this
    shape (see context_collectors.py); the journal stores and serves it.
    """

    id: Optional[str] = None
    source_id: str = ""
    kind: str = "other"  # calendar | mail | chat | vcs | other
    provider: str = ""
    start_ts: float = 0.0
    end_ts: Optional[float] = None
    title: str = ""
    participants: List[str] = Field(default_factory=list)
    project_hint: Optional[str] = None
    summary: Optional[str] = None
    collected_at: float = 0.0
