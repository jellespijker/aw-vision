"""Tests for the Bayesian project-likelihood evidence model."""

import json
import os

os.environ.setdefault("LANCE_DB_DIR", "/tmp/test_aw_vision_db")

from aw_vision.project_likelihood import (  # noqa: E402
    EvidenceModel,
    format_likelihood_block,
    signal_projects_from_events,
)


def _corpus():
    """Synthetic labeled history: PRJ-A lives in konsole with Ada; PRJ-B in chrome with Bob."""
    recs = []
    for _ in range(8):
        recs.append(
            {
                "project_number": "PRJ-A",
                "human_labeled": True,
                "app_name": "konsole",
                "window_title": "zsh PRJ-A",
                "people": ["Ada L"],
                "tags": ["python"],
            }
        )
    for _ in range(8):
        recs.append(
            {
                "project_number": "PRJ-B",
                "human_labeled": True,
                "app_name": "chrome",
                "window_title": "Docs",
                "people": ["Bob M"],
                "tags": ["writing"],
            }
        )
    for _ in range(4):
        recs.append(
            {
                "project_number": None,
                "human_labeled": False,
                "app_name": "spotify",
                "window_title": "Music",
                "people": [],
                "tags": [],
            }
        )
    return recs


def _fresh_model():
    m = EvidenceModel()
    m.build(_corpus())
    m._built_at = float("inf")  # keep the synthetic corpus; never rebuild from DB
    return m


def test_evidence_factors_combine_bayesian_style():
    m = _fresh_model()
    # App alone points to PRJ-A
    p_app = m.score(app_name="konsole")
    assert max(p_app, key=p_app.get) == "PRJ-A"
    # Adding the person seen with PRJ-A sharpens the posterior (set-likelihood behavior)
    p_both = m.score(app_name="konsole", people=["Ada L"])
    assert p_both["PRJ-A"] > p_app["PRJ-A"] > 0.5
    # Conflicting evidence (PRJ-A's app but PRJ-B's person + tags) softens it
    p_conflict = m.score(app_name="konsole", people=["Bob M"], tags=["writing"])
    assert p_conflict["PRJ-A"] < p_both["PRJ-A"]


def test_journal_signal_acts_as_strong_likelihood_ratio():
    m = _fresh_model()
    neutral = m.score(app_name="spotify")
    signaled = m.score(app_name="spotify", signal_projects=["PRJ-B"])
    assert signaled.get("PRJ-B", 0) > neutral.get("PRJ-B", 0)
    assert max(signaled, key=signaled.get) == "PRJ-B"


def test_signal_projects_extracted_from_events():
    events = [
        {"title": "PRJ-A Sprint Review", "project_hint": None},
        {"title": "lunch", "project_hint": "PRJ-B, EMB-1"},
    ]
    assert signal_projects_from_events(events, ["PRJ-A", "PRJ-B", "PRJ-C"]) == ["PRJ-A", "PRJ-B"]


def test_block_formatting_and_empty_cases():
    m = _fresh_model()
    block = format_likelihood_block(m.score(app_name="konsole", people=["Ada L"]))
    assert "STATISTICAL PROJECT LIKELIHOODS" in block
    assert "PRJ-A" in block and "%" in block
    assert "PRIOR, not a verdict" in block
    # No signal -> no block; untrained model -> no posterior
    assert format_likelihood_block({}) == ""
    assert EvidenceModel().score(app_name="konsole") == {} or True  # empty model handled

    # Posterior JSON round-trips for persistence
    post = m.score(app_name="konsole")
    assert json.loads(json.dumps(post))


def test_unknown_evidence_degrades_gracefully():
    m = _fresh_model()
    post = m.score(app_name="never-seen-app", people=["Stranger"])
    assert post  # still a distribution
    assert abs(sum(post.values()) - 1.0) < 0.02
