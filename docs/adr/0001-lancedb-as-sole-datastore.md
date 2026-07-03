# ADR-0001: LanceDB as the sole datastore

- **Status:** Accepted
- **Date:** 2026-07-03 (retroactive; decision predates ADRs)

## Context
The product needs vector search over screenshot embeddings plus persistence for settings, prompts, skills, MCP configs, and snapshot metadata — all local-first, zero-ops, single user.

## Decision
Use embedded LanceDB for everything: the vector table (`screenshots`) and all key/value–style config tables. No external database processes.

## Consequences
Zero-ops and a single storage location to back up. Costs accepted knowingly: no SQL joins or server-side ordering in the current query layer (full scans + Python sorts), schema migration is drop-and-recreate, and key/value tables are hand-rolled per store (dedup planned via a shared store abstraction). Revisit trigger: history queries becoming user-visibly slow (>1 s) at the current growth rate, or LanceDB FTS proving insufficient for hybrid search.
