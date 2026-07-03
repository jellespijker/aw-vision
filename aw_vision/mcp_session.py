"""Persistent MCP sessions and per-server circuit breaking.

The previous facade opened a fresh transport + event loop + ClientSession for
EVERY tool call — for a docker-based stdio server that meant one `docker run`
per call, and a dead server assigned to a pipeline slot cost a full timeout
per screenshot. This module gives each server:

- a ``SessionWorker``: one long-lived ClientSession on a dedicated event-loop
  thread, reaped after ``IDLE_TIMEOUT`` of inactivity;
- a ``CircuitBreaker``: after ``FAILURE_THRESHOLD`` consecutive failures the
  server is skipped for ``COOLDOWN_SECONDS`` instead of timing out every call.
"""

import asyncio
import threading
import time
from contextlib import AsyncExitStack
from typing import Any, Callable, Dict, Optional

IDLE_TIMEOUT = 300.0
FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 120.0


class CircuitBreaker:
    """Consecutive-failure breaker with a cooldown window."""

    def __init__(self):
        self.failures = 0
        self.open_until = 0.0
        self.last_error: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return time.time() < self.open_until

    def record_success(self):
        self.failures = 0
        self.open_until = 0.0
        self.last_error = None

    def record_failure(self, error: str):
        self.failures += 1
        self.last_error = error[:300]
        if self.failures >= FAILURE_THRESHOLD:
            self.open_until = time.time() + COOLDOWN_SECONDS

    def health(self) -> Dict[str, Any]:
        return {
            "state": "open" if self.is_open else ("degraded" if self.failures else "ok"),
            "consecutive_failures": self.failures,
            "last_error": self.last_error,
            "retry_at": self.open_until if self.is_open else None,
        }


class SessionWorker:
    """Owns one persistent, initialized ClientSession on a private event loop thread."""

    def __init__(self, cfg: Dict[str, Any], open_transport: Callable):
        """``open_transport(stack, cfg)`` is an async fn entering the transport +
        session context managers on ``stack`` and returning the initialized session."""
        self.cfg = cfg
        self._open_transport = open_transport
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._stack: Optional[AsyncExitStack] = None
        self.session = None
        self.last_used = time.time()
        self._thread.start()

    def _run(self, coro, timeout: float):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def open(self, timeout: float = 30.0):
        async def _open():
            stack = AsyncExitStack()
            session = await self._open_transport(stack, self.cfg)
            return stack, session

        self._stack, self.session = self._run(_open(), timeout)
        self.last_used = time.time()

    def call(self, action: Callable, timeout: float = 45.0):
        """Run ``await action(session)`` on the worker loop."""
        self.last_used = time.time()
        return self._run(action(self.session), timeout)

    def close(self, timeout: float = 10.0):
        try:
            if self._stack is not None:
                self._run(self._stack.aclose(), timeout)
        except Exception:
            pass
        finally:
            self._stack = None
            self.session = None
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)


class SessionPool:
    """Lazy per-server workers with config-change invalidation and idle reaping."""

    def __init__(self, open_transport: Callable, cache_key: Callable[[Dict[str, Any]], str]):
        self._open_transport = open_transport
        self._cache_key = cache_key
        self._workers: Dict[str, SessionWorker] = {}
        self._keys: Dict[str, str] = {}
        self.breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def breaker(self, server_id: str) -> CircuitBreaker:
        with self._lock:
            return self.breakers.setdefault(server_id, CircuitBreaker())

    def _evict_locked(self, server_id: str):
        worker = self._workers.pop(server_id, None)
        self._keys.pop(server_id, None)
        if worker:
            threading.Thread(target=worker.close, daemon=True).start()

    def reap_idle(self):
        now = time.time()
        with self._lock:
            for sid, worker in list(self._workers.items()):
                if now - worker.last_used > IDLE_TIMEOUT:
                    self._evict_locked(sid)

    def invalidate(self, server_id: str):
        with self._lock:
            self._evict_locked(server_id)

    def acquire(self, cfg: Dict[str, Any], timeout: float = 30.0) -> SessionWorker:
        """Return a live worker for ``cfg``, (re)opening if absent or config changed."""
        self.reap_idle()
        sid = cfg["id"]
        key = self._cache_key(cfg)
        with self._lock:
            worker = self._workers.get(sid)
            if worker is not None and self._keys.get(sid) == key:
                return worker
            if worker is not None:
                self._evict_locked(sid)

        worker = SessionWorker(cfg, self._open_transport)
        try:
            worker.open(timeout=timeout)
        except Exception:
            worker.close()
            raise
        with self._lock:
            self._workers[sid] = worker
            self._keys[sid] = key
        return worker

    def call(self, cfg: Dict[str, Any], action: Callable, timeout: float = 45.0):
        """Breaker-guarded call with one automatic session-rebuild retry.

        A failure on a previously healthy session usually means the transport
        died (server restarted); we rebuild once before charging the breaker.
        """
        sid = cfg["id"]
        breaker = self.breaker(sid)
        if breaker.is_open:
            raise ConnectionError(
                f"MCP server '{cfg.get('name', sid)}' circuit is open after "
                f"{breaker.failures} consecutive failures: {breaker.last_error}"
            )
        try:
            try:
                worker = self.acquire(cfg, timeout=min(timeout, 30.0))
                result = worker.call(action, timeout=timeout)
            except Exception:
                self.invalidate(sid)
                worker = self.acquire(cfg, timeout=min(timeout, 30.0))
                result = worker.call(action, timeout=timeout)
            breaker.record_success()
            return result
        except Exception as e:
            breaker.record_failure(str(e))
            self.invalidate(sid)
            raise
