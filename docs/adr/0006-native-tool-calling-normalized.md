# ADR-0006: Native tool calling normalized onto the CALL_TOOL representation

- **Status:** Accepted
- **Date:** 2026-07-03
- **Context links:** ADR-0002 (revisit), ADR-0005 (supersedes)

## Context
The CALL_TOOL text protocol required three regex repair heuristics for models that narrate instead of emitting the line. Ollama and Gemini now support structured tool calling, but some local model templates (notably Gemma variants) still reject `tools=` at runtime — support cannot be assumed per provider, only probed per model.

## Decision
The Memory Agent tries Ollama's native `tools=` chat API first (`tooling.ollama_chat_native`); structured calls are **normalized back into the canonical `CALL_TOOL` line**, so the LangGraph flow, loop guard, streaming and logs are unchanged. Models that reject tools are memoized per model and use the text protocol; the repair heuristics run **only** on the text path (on the native path, a reply without a call *is* the final answer). The transitional dual `ToolCall`/`ToolEvent` representations from ADR-0005 are unified on `ToolEvent` end-to-end (stream events included).

## Consequences
Tool-capable models get reliable, typed calls with zero regex repair; non-capable models lose nothing. The pipeline ReAct loop still speaks the text protocol (its `format=json` constraint conflicts with native calls) — extend natively when a tool-capable local model becomes the pipeline default. Gemini agent chat keeps the text protocol until function-calling is wired into `gemini/chat.py` (open item).
