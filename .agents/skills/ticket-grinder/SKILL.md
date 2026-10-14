---
name: ticket-grinder
description: Run the autonomous backlog ticket loop with delegated workers and independent verification. Use when the user requests the ticket-grinder workflow.
---

# ticket-grinder

Read repository `AGENTS.md`, `CLAUDE.md` and the canonical workflow in
[.claude/agents/ticket-grinder.md](../../../.claude/agents/ticket-grinder.md).
Follow its scope, state ownership, verification and stop conditions.
Resolve project paths from the repository root and use `.agents/skills/`
for the project skills it names. Do not start ticket work while installing
or editing this skill.

## Codex adaptation

Run in the main agent. Translate Claude's Agent tool / subagent_type ticket-worker
into the available Codex subagent tool, instructing each worker to read
`.agents/skills/ticket-worker/SKILL.md`. Supply ticket ID, backlog text and
workingOn.md block. This workflow explicitly requests delegation; parallel
workers must touch disjoint files. If delegation tools are unavailable,
report the limitation before starting the loop.

Ignore Claude's model metadata and CLI invocation; inherit the current Codex
model and effort unless the user requests otherwise. Invoke with `$ticket-grinder`.

Commit and push only when authorized by the user for this run, per CLAUDE.md.
A request to implement tickets alone does not grant that authorization. Without
it, finish and verify the first eligible ticket, report the reviewable result,
and stop before committing or pushing. Respect sandbox and approval requirements.
