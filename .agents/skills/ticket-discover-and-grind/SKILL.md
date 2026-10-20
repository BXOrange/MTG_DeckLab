---
name: ticket-discover-and-grind
description: Discover verified Commander coverage tickets and run bounded implementation loops with independent verification. Use for ticket-discover-and-grind; ticket-grinder remains the existing-backlog variant.
---

# ticket-discover-and-grind

Read repository `AGENTS.md`, `CLAUDE.md` and the canonical workflow in
[.claude/agents/ticket-discover-and-grind.md](../../../.claude/agents/ticket-discover-and-grind.md).
Follow its scope, state ownership, verification and stop conditions.
Resolve project paths from the repository root and use `.agents/skills/`
for the project skills it names. Do not start ticket work while installing
or editing this skill.

## Codex adaptation

Run in the main agent. Translate Claude's Agent tool / subagent_type ticket-worker
into the available Codex subagent tool, instructing each worker to read
`.agents/skills/ticket-worker/SKILL.md`. Supply ticket ID, backlog text and
workingOn.md block, run identity, code-content digest and isolated snapshot
paths/environment from the canonical workflow. For coverage discovery, delegate the read-only role through
`.agents/skills/coverage-discovery/SKILL.md`, supplying revision, pool
fingerprint, support scope and artifact directory. This workflow explicitly
requests delegation; run one implementation worker at a time. If delegation
tools are unavailable, report the limitation before starting the loop.

Ignore Claude's model metadata and CLI invocation; inherit the current Codex
model and effort unless the user requests otherwise. Invoke with `$ticket-discover-and-grind`.

Resolve continuation, commit and push permissions separately using the
canonical workflow. Lack of push permission alone does not prohibit
otherwise-authorized local commits or continuation. Respect sandbox approvals.

Invoke `$ticket-discover-and-grind` for Commander coverage discovery and
promotion. Use the separate `$ticket-grinder` for the original backlog loop. Do not start ticket work while editing
or installing this workflow; perform the pilot in a separate invocation.

Example run request after installation, in an available owned checkout:

> Use $ticket-discover-and-grind for the one-ticket pilot.
> You may commit and push to a dedicated branch; do not merge. Retain the
> support exclusions. Stop after verification and delivery, and report the
> evidence, coverage delta and result.

After a successful inspected pilot, request up to 10 tickets with the same
permissions. Never take over another session's active ticket automatically.
