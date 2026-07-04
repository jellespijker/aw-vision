# ADR-0002: CALL_TOOL text protocol for agent tool use

- **Status:** Accepted (revisit planned)
- **Date:** 2026-07-03 (retroactive)

## Context
The Memory Agent and pipeline ReAct prompts need tool invocation that works across providers, including small local models that historically lacked reliable structured tool calling.

## Decision
A single text protocol — `CALL_TOOL: name, argument` — parsed by `tooling.parse_tool_call`, shared by every agent. Heuristic fallback parsers in `agent.py` compensate for models that narrate instead of emitting the line.

## Consequences
Provider-agnostic and debuggable in plain logs, but fragile: three regex fallbacks exist solely to repair non-conforming replies, and results are stringly typed. Revisit trigger (planned): migrate `tooling.py` to native structured tool calling (Ollama `tools=`, Gemini function calling), deleting the fallbacks; keep the text protocol only as a last-resort fallback for models without tool support.
