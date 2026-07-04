"""Tests for the provider-agnostic external context journal."""

import os
import subprocess
import time
from pathlib import Path

os.environ.setdefault("LANCE_DB_DIR", "/tmp/test_aw_vision_db")

from aw_vision.context_collectors import (  # noqa: E402
    collect_git_local,
    normalize_with_llm,
    project_hint_from_text,
    run_source_command,
)
from aw_vision.context_journal import ContextJournal, ContextSourceStore, normalize_source  # noqa: E402
from aw_vision.models import ExternalEvent  # noqa: E402


def test_project_hint_extraction():
    assert project_hint_from_text("PRJ-2026-042_native_tool_calling refs EMB-467") == "EMB-467, PRJ-2026-042"
    assert project_hint_from_text("no keys here") == ""


def test_source_normalization_and_command_whitelist():
    src = normalize_source({"name": "MS mail", "kind": "mail", "method": "command", "command": "rm"})
    try:
        run_source_command(src, 0, 1)
        raise AssertionError("expected whitelist rejection")
    except ValueError as e:
        assert "not in the context-source whitelist" in str(e)
    # Neutral schema: nothing provider-specific is required
    assert src["kind"] == "mail" and src["enabled"] is False


def test_git_local_collector_derives_project_hints(tmp_path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Jelle T",
        "GIT_AUTHOR_EMAIL": "j@x",
        "GIT_COMMITTER_NAME": "Jelle T",
        "GIT_COMMITTER_EMAIL": "j@x",
    }
    subprocess.run(["git", "init", "-q", "-b", "PRJ-2026-042_feature_x", str(repo)], check=True, env=env)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "Implement EMB-467 heater"], check=True, env=env)

    src = normalize_source(
        {"id": "gitloc", "name": "git", "kind": "vcs", "method": "git_local", "repos_root": str(tmp_path)}
    )
    events = collect_git_local(src, time.time() - 3600, time.time() + 60)
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "vcs" and ev.provider == "git"
    assert "EMB-467" in ev.title or "EMB-467" in (ev.project_hint or "")
    assert "PRJ-2026-042" in (ev.project_hint or "")
    assert ev.participants == ["Jelle T"]


def test_journal_insert_query_and_prompt_block():
    store = ContextSourceStore()
    journal = ContextJournal(store)
    journal.table.delete("source_id = 's1'")  # leftovers from previous runs
    now = time.time()
    inserted = journal.insert_events(
        [
            ExternalEvent(
                source_id="s1",
                kind="calendar",
                provider="google",
                start_ts=now - 300,
                end_ts=now + 300,
                title="EMB-467 Sprint Review",
                participants=["Casper Lambo"],
                project_hint="EMB-467",
            ),
            ExternalEvent(
                source_id="s1",
                kind="calendar",
                provider="microsoft",
                start_ts=now - 86400,
                title="Old event outside window",
            ),
        ]
    )
    assert inserted == 2
    # Idempotent re-insert (same id => the row is replaced, not duplicated)
    journal.insert_events(
        [
            ExternalEvent(
                source_id="s1",
                kind="calendar",
                provider="google",
                start_ts=now - 300,
                end_ts=now + 300,
                title="EMB-467 Sprint Review",
                participants=["Casper Lambo"],
                project_hint="EMB-467",
            )
        ]
    )
    rows = journal.events_around(now)
    titles = [r["title"] for r in rows]
    assert titles.count("EMB-467 Sprint Review") == 1
    assert "Old event outside window" not in titles

    block = journal.build_external_events_block(now)
    assert "CONCURRENT EXTERNAL EVENTS" in block
    assert "EMB-467 Sprint Review" in block and "PROJECT SIGNAL: EMB-467" in block
    assert "Casper Lambo" in block
    # Clean up journal rows for repeatability
    journal.table.delete("source_id = 's1'")


def test_normalizer_is_provider_agnostic(monkeypatch):
    """The same normalizer converts Google-ish and Microsoft-ish raw output alike (LLM mocked)."""
    import aw_vision.context_collectors as cc

    now = time.time()

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "response": '{"events": [{"title": "Weekly sync", "start_ts": %f, '
                '"participants": ["Ada L"], "project_hint": "PRJ-2026-042"}]}' % now
            }

    monkeypatch.setattr(cc.__dict__["normalize_with_llm"].__globals__["json"], "loads", __import__("json").loads)
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
    for provider in ("Google Workspace", "Microsoft 365"):
        src = normalize_source(
            {"id": "x", "name": provider, "kind": "calendar", "method": "command", "provider_label": provider}
        )
        events = normalize_with_llm("raw provider payload", src)
        assert len(events) == 1
        assert events[0].title == "Weekly sync"
        assert events[0].provider == provider
        assert events[0].project_hint == "PRJ-2026-042"
