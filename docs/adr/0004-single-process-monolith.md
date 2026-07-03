# ADR-0004: Single-process monolith (capture + pipeline + API)

- **Status:** Accepted (revisit planned)
- **Date:** 2026-07-03 (retroactive)

## Context
Watcher, batch processor, agent, and HTTP API currently share one uvicorn process, guarded against duplicate instances by a startup port check.

## Decision
Keep a single deployable for simplicity; systemd restarts the whole unit.

## Consequences
Simple deployment, shared in-memory state. Known failure class: uvicorn `--reload` and restart races interact badly with the port guard (background daemons silently skipped); hot reloads kill in-flight jobs. Revisit trigger (planned): split into `aw-vision-capture` (watcher + processor) and `aw-vision-api` (API + agent + SPA) systemd services communicating via LanceDB and the shared screenshots directory.
