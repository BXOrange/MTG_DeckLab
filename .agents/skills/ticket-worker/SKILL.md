---
name: ticket-worker
description: Implement one assigned backlog ticket using the matching project skill and tests. Use for delegated ticket work; does not commit, push, select or close tickets.
---

# ticket-worker

Read repository `AGENTS.md`, `CLAUDE.md` and the canonical workflow in
[.claude/agents/ticket-worker.md](../../../.claude/agents/ticket-worker.md).
Follow its scope, state ownership, verification and stop conditions.
Resolve project paths from the repository root and use `.agents/skills/`
for the project skills it names. Do not start ticket work while installing
or editing this skill.

## Codex adaptation

Inherit the current Codex model and effort; Claude's model: sonnet and
effort: medium are not Codex settings. The orchestrator supplies the ticket ID,
backlog text and workingOn.md block. When invoked directly with `$ticket-worker`
without an assigned ticket, obtain the assignment before implementation.
Do not commit, push, select or close tickets.
