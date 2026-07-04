"""Bayesian project likelihoods learned from the user's own labeled history.

Instead of a single hard label, every snapshot gets a probability distribution
over projects, combined naive-Bayes style from independent evidence factors:

    P(project | evidence) ∝ P(project) · ∏ P(factor | project)

Factors observed per snapshot: the application, the people involved, the
tags, ticket/project keys in the window title, and concurrent journal events
(calendar/mail/chat/VCS). Conditional frequencies come from previously
labeled snapshots — human labels weigh 5× (consistent with the rest of the
system) — with Laplace smoothing, so the model sharpens as the corpus grows.
That is precisely why reprocessing old snapshots later genuinely improves
them: they are re-scored against everything learned since.

The posterior is a PRIOR for the LLM (injected as evidence, never a verdict)
and is persisted per snapshot for the UI and reporting.
"""

import json
import math
import time
from typing import Any, Dict, List, Optional

from aw_vision.context_collectors import PROJECT_KEY_RE

NONE_CLASS = "None"
HUMAN_WEIGHT = 5.0
ALPHA = 0.5  # Laplace smoothing
# Fixed likelihood ratio for a concurrent journal event that names a catalog
# project outright (calendar title / branch key): strong, near-deterministic.
SIGNAL_LOG_LR = math.log(10.0)
REBUILD_TTL = 600.0


def _features_of(app_name: str, window_title: str, people: List[str], tags: List[str]) -> List[str]:
    """The per-snapshot evidence features, factor-prefixed."""
    feats: List[str] = []
    if app_name and app_name != "Unknown":
        feats.append(f"app:{app_name.lower()}")
    for key in set(PROJECT_KEY_RE.findall(window_title or "")):
        feats.append(f"key:{key}")
    for p in people or []:
        if p and str(p).strip():
            feats.append(f"person:{str(p).strip().lower()}")
    for t in tags or []:
        if t and str(t).strip():
            feats.append(f"tag:{str(t).strip().lower()}")
    return feats


class EvidenceModel:
    """Naive-Bayes counts over the labeled corpus, rebuilt lazily with a TTL."""

    def __init__(self):
        self._built_at = 0.0
        self.class_counts: Dict[str, float] = {}
        self.feature_counts: Dict[str, Dict[str, float]] = {}  # class -> feature -> weighted count
        self.vocab: Dict[str, set] = {}  # factor prefix -> distinct values seen

    # -- training --------------------------------------------------------------
    def build(self, records: List[Dict[str, Any]]):
        self.class_counts = {}
        self.feature_counts = {}
        self.vocab = {}
        for r in records:
            cls = (r.get("project_number") or NONE_CLASS).strip() or NONE_CLASS
            weight = HUMAN_WEIGHT if r.get("human_labeled") else 1.0
            self.class_counts[cls] = self.class_counts.get(cls, 0.0) + weight
            bucket = self.feature_counts.setdefault(cls, {})
            for f in _features_of(
                r.get("app_name") or "", r.get("window_title") or "", r.get("people") or [], r.get("tags") or []
            ):
                bucket[f] = bucket.get(f, 0.0) + weight
                self.vocab.setdefault(f.split(":", 1)[0], set()).add(f)
        self._built_at = time.time()

    def ensure_fresh(self):
        if time.time() - self._built_at < REBUILD_TTL:
            return
        try:
            from aw_vision.db import db

            self.build(db.get_all_records(limit=100000))
        except Exception as e:
            print(f"[Likelihood] model rebuild failed: {e}")
            self._built_at = time.time()  # back off, retry after TTL

    # -- inference ---------------------------------------------------------------
    def score(
        self,
        app_name: str = "",
        window_title: str = "",
        people: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        signal_projects: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> Dict[str, float]:
        """Posterior P(project | evidence) over known classes, normalized.

        ``signal_projects`` are catalog projects named outright by concurrent
        journal events; each contributes a fixed log-likelihood ratio.
        """
        self.ensure_fresh()
        total = sum(self.class_counts.values())
        if total <= 0 or len(self.class_counts) < 2:
            return {}

        feats = _features_of(app_name, window_title, people or [], tags or [])
        n_classes = len(self.class_counts)
        log_post: Dict[str, float] = {}
        for cls, c_count in self.class_counts.items():
            lp = math.log((c_count + 1.0) / (total + n_classes))
            bucket = self.feature_counts.get(cls, {})
            for f in feats:
                factor = f.split(":", 1)[0]
                vocab_size = max(1, len(self.vocab.get(factor, ())))
                lp += math.log((bucket.get(f, 0.0) + ALPHA) / (c_count + ALPHA * vocab_size))
            for sp in signal_projects or []:
                if cls == sp:
                    lp += SIGNAL_LOG_LR
            log_post[cls] = lp

        # Normalize in log space
        m = max(log_post.values())
        exp = {c: math.exp(v - m) for c, v in log_post.items()}
        z = sum(exp.values())
        post = {c: v / z for c, v in exp.items()}
        top = sorted(post.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return {c: round(p, 4) for c, p in top}


def signal_projects_from_events(events: List[Dict[str, Any]], catalog_numbers: List[str]) -> List[str]:
    """Catalog projects named outright in concurrent journal events' hints/titles."""
    hits = set()
    for ev in events or []:
        blob = f"{ev.get('project_hint') or ''} {ev.get('title') or ''}"
        for num in catalog_numbers:
            if num and num in blob:
                hits.add(num)
    return sorted(hits)


def format_likelihood_block(posterior: Dict[str, float]) -> str:
    """Prompt-ready statistical-prior block ("" when the model has no signal)."""
    if not posterior:
        return ""
    best = max(posterior.values())
    if best < 0.2:
        return ""
    lines = [
        "STATISTICAL PROJECT LIKELIHOODS (Bayesian, learned from this user's previously "
        "labeled snapshots: application, people, tags, ticket keys and concurrent "
        "calendar/VCS events). This is a PRIOR, not a verdict — use it to break ties on "
        "thematic evidence; NEVER let it override direct contrary on-screen evidence:"
    ]
    for cls, p in posterior.items():
        lines.append(f"- {cls}: {p * 100:.0f}%")
    return "\n".join(lines) + "\n\n"


evidence_model = EvidenceModel()
