# ADR-0005: Transitional dual tool-call representations (ToolCall + ToolEvent)

- **Status:** Accepted (transitional)
- **Date:** 2026-07-03
- **Context links:** PR #23, PR #30, PR #33

## Context
PR #23 introduced live SSE streaming of agent tool calls (`ToolCall {name, arg, result}`); PR #30 independently introduced the unified tool layer with structured events (`ToolEvent {tool, args, source, duration, error}`). The integration merge (PR #33) had to reconcile both without rewriting either under review pressure.

## Decision
Keep both temporarily: the SSE stream and its live UI speak `ToolCall`; the graph state, `/api/query`, and the message cards speak `ToolEvent`. `ChatMessage` carries both optional fields.

## Consequences
No functionality lost in the merge, but one concept has two shapes (a DRY violation by design). Revisit trigger: the next change touching either path must unify on `ToolEvent` end-to-end (stream events included) and delete `ToolCall`.
