# ADR-0003: Hardware-derived encryption key for secrets at rest

- **Status:** Accepted (known limitation)
- **Date:** 2026-07-03 (retroactive)

## Context
API keys and MCP tokens must be encrypted at rest without prompting the user for a passphrase on every daemon start (headless systemd services).

## Decision
Derive the Fernet key from hostname + home path + MAC address (`settings.get_encryption_key`). No key file on disk, no passphrase.

## Consequences
Zero-friction and better than plaintext, but the key silently changes when the hostname or NIC changes, bricking all stored secrets with only decrypt-error logs as a symptom. Accepted for a single-machine product. Revisit trigger: first user report of secret loss after a hardware change — then add an explicit key file with export/re-key tooling.
