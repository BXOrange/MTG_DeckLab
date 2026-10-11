---
name: understand-card
description: Analyze an MTG card's Oracle text, governing Comprehensive Rules, parser coverage and bound effects before parser or engine changes.
---

# understand-card

Read and follow the shared workflow in
[.claude/skills/understand-card/SKILL.md](../../../.claude/skills/understand-card/SKILL.md)
before performing this task. That file is the canonical implementation of this
skill for both Claude Code and Codex.

Resolve its relative links, scripts and references against
`.claude/skills/understand-card/`, not this entrypoint. Run the existing helpers
at their original paths; do not copy or reimplement them.

Read repository `AGENTS.md` and the routed project documentation first.
Adapt shell examples to the current platform. On Windows, use the available
backend virtual environment's `Scripts/python.exe` directly instead of Bash
activation; on POSIX use its `bin/python`. Preserve the documented working
directory and command arguments.

