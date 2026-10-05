---
name: singleton-sweeper
description: Re-check a parser singleton against the full cached MTG card pool, group similar unclaimed Oracle-text clauses, and promote real shared shapes into one PAR ticket while removing related rows from the singleton queue.
---

# Sweeping a parser singleton

Use this before hand-authoring a card listed in
[`docs/implementation-state/singletons.md`](../../../docs/implementation-state/singletons.md).
A previous singleton verdict can go stale when unrelated parser work lands:
the card may now share a useful shape with other cards. The goal is to find
that shared parser work before treating the card as a one-off.

```bash
cd backend && source venv/bin/activate
SWEEPER=../.claude/skills/singleton-sweeper/scripts/singleton_sweeper.py
python $SWEEPER "Card Name"
```

The script reads the entire local card cache by default. For each currently
unclaimed clause on the target, it compares unclaimed clauses across cached
cards, groups exact template matches using the parser's own `abstract_clause`
logic, then lists fuzzy neighboring templates by text similarity. Results
include unique card names and candidate clauses. Use `author_card.py check`
when you need to establish whether a candidate is already hand-authored. The
helper opens the cache read-only and never edits the cache, coverage ledger,
or project-state files.

`--limit N` is only for a quick smoke check; do not use it to decide whether a
card is genuinely singleton. `--threshold 0.5` adjusts the fuzzy discovery
threshold. Text similarity is a lead, not proof: compare full Oracle text and
the parser's claimed/unclaimed boundaries before deciding that cards share
one grammar shape.

## Workflow

1. **Verify the queue entry and current gap.** Run the sweep on the exact card
   name. If the card has no parser-unclaimed clauses now, check whether its
   row is still in `singletons.md`: remove a stale row only after confirming
   the card is now `MODELED`, already `AUTHORED`, or intentionally
   `NEVER_SUPPORTED`. Do not create a parser ticket for a gap that no longer
   exists.
2. **Decide whether candidates share a parser shape.** Inspect the exact
   template group first, then review fuzzy groups for the same rules-relevant
   structure. Similar words alone are insufficient. Check each candidate's
   complete `parser_probe.py card "<name>"` output where necessary, and use
   `parser_probe.py blocked "<bounded regex>"` to measure the real SOLO and
   ALSO-BLOCKED card sets for the shared clause. The latter distinguishes
   cards genuinely unlocked by one handler from cards with additional gaps.
3. **Check existing work before opening a ticket.** Search `BACKLOG.md`,
   `DEFERRED.md`, and `Done_Backend.md` for the shape and candidate cards.
   If an open PAR ticket already covers it, refine that ticket rather than
   duplicating it. A fuzzy suggestion is not enough to reopen shipped work;
   establish a current uncovered cluster first.
4. **Promote a confirmed cluster together.** When the target and at least one
   other card share a generalizable unclaimed shape, create or refine one
   parser (`PAR-*`) ticket for the common grammar axis, not one ticket per
   card. Write actionable open scope only, include representative card names
   and the measured scope where useful, and size it through the
   `extend-parser` workflow. Before assigning an ID, verify the next free PAR
   ID against the current backlog and worklogs; stale ID hints are not
   authoritative.
5. **Refactor related singleton rows in the same pass.** Search
   `singletons.md` for every confirmed member of the shared group. Remove
   those rows from the singleton queue and make the common ticket their
   tracked home. Leave unrelated cards in place. Do not move a card based on
   a fuzzy-only match until its shared parser shape is verified.
6. **If it remains a singleton**, keep its queue row unchanged and hand it to
   [`hand-author-card`](../hand-author-card/SKILL.md). If work produces a
   shared parser capability, use `ticket-management` to keep the ticket,
   singleton queue, and later worklog consistent.

The ticket and queue follow the repository's state rules in
[`ticket-management`](../ticket-management/SKILL.md): backlog entries are
open scope only; completed singleton rows are deleted; durable implementation
narrative belongs in `Done_Backend.md`, not in the queue.
