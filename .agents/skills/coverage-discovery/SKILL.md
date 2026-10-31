---
name: coverage-discovery
description: Investigate Commander coverage gaps read-only and return measured candidates to ticket-discover-and-grind. Use for delegated coverage discovery; does not implement, allocate tickets or edit tracking.
---

# coverage-discovery

Read repository `AGENTS.md`, `CLAUDE.md` and the canonical role in
[.claude/agents/coverage-discovery.md](../../../.claude/agents/coverage-discovery.md).
Follow its bounded investigation, read-only boundaries and return contract.
Resolve paths from the repository root; use `.agents/skills/` for its named
project skills. Inherit the current Codex model and effort; ignore Claude
model metadata.

The orchestrator supplies revision, pool fingerprint, support scope and
artifact directory. If invoked without those, obtain the assignment before
claiming verified scope. Return evidence to the orchestrator; do not perform
the ticket/queue-writing parts of singleton-sweeper or ticket-management.
