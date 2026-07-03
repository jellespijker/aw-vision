"""Tests for persistent MCP sessions and circuit breaking (no live servers)."""

import os
import time

os.environ.setdefault("LANCE_DB_DIR", "/tmp/test_aw_vision_db")

from aw_vision import mcp_session  # noqa: E402
from aw_vision.mcp_session import CircuitBreaker, SessionPool  # noqa: E402


class _DummySession:
    def __init__(self, tag):
        self.tag = tag


def _make_transport(fail_flag):
    opened = {"count": 0}

    async def open_transport(stack, cfg):
        if fail_flag["fail"]:
            raise ConnectionError("boom")
        opened["count"] += 1
        return _DummySession(f"{cfg['id']}-{opened['count']}")

    return open_transport, opened


async def _tag_action(session):
    return session.tag


def test_breaker_opens_after_threshold_and_recovers():
    br = CircuitBreaker()
    assert br.health()["state"] == "ok"
    for _ in range(mcp_session.FAILURE_THRESHOLD - 1):
        br.record_failure("x")
    assert not br.is_open
    assert br.health()["state"] == "degraded"
    br.record_failure("final")
    assert br.is_open
    assert br.health()["state"] == "open"
    br.record_success()
    assert not br.is_open
    assert br.health()["state"] == "ok"


def test_pool_reuses_session_and_invalidates_on_config_change():
    fail = {"fail": False}
    transport, opened = _make_transport(fail)
    pool = SessionPool(transport, cache_key=lambda cfg: cfg.get("command", ""))
    cfg = {"id": "srv1", "name": "S1", "command": "a"}
    try:
        assert pool.call(cfg, _tag_action) == "srv1-1"
        # Same config: session reused, not reopened.
        assert pool.call(cfg, _tag_action) == "srv1-1"
        assert opened["count"] == 1
        # Changed config: new session.
        cfg2 = {**cfg, "command": "b"}
        assert pool.call(cfg2, _tag_action) == "srv1-2"
        assert opened["count"] == 2
    finally:
        pool.invalidate("srv1")


def test_pool_trips_breaker_and_blocks_until_cooldown(monkeypatch):
    fail = {"fail": True}
    transport, _ = _make_transport(fail)
    pool = SessionPool(transport, cache_key=lambda cfg: "k")
    cfg = {"id": "srv2", "name": "S2"}

    for _ in range(mcp_session.FAILURE_THRESHOLD):
        try:
            pool.call(cfg, _tag_action, timeout=5.0)
            raise AssertionError("expected failure")
        except ConnectionError:
            pass
    # Circuit is now open: calls are rejected without touching the transport.
    try:
        pool.call(cfg, _tag_action, timeout=5.0)
        raise AssertionError("expected open-circuit rejection")
    except ConnectionError as e:
        assert "circuit is open" in str(e)

    # After cooldown (simulated), a healthy transport recovers the server.
    fail["fail"] = False
    pool.breaker("srv2").open_until = time.time() - 1
    try:
        assert pool.call(cfg, _tag_action, timeout=5.0).startswith("srv2-")
        assert pool.breaker("srv2").health()["state"] == "ok"
    finally:
        pool.invalidate("srv2")


def test_idle_reap_evicts_stale_workers():
    fail = {"fail": False}
    transport, opened = _make_transport(fail)
    pool = SessionPool(transport, cache_key=lambda cfg: "k")
    cfg = {"id": "srv3", "name": "S3"}
    try:
        pool.call(cfg, _tag_action)
        assert opened["count"] == 1
        # Age the worker beyond the idle timeout and trigger a reap via the next call.
        pool._workers["srv3"].last_used = time.time() - mcp_session.IDLE_TIMEOUT - 1
        pool.call(cfg, _tag_action)
        assert opened["count"] == 2
    finally:
        pool.invalidate("srv3")
