---
name: ticket-management
description: Create, refine, start, resume, park, and close project tickets while keeping BACKLOG.md, workingOn.md, DEFERRED.md, and Done_* documentation consistent.
---

# Ticket management

Use this skill for ticket lifecycle and implementation-state documentation.
It organizes work; it does not implement a ticket unless the user also asks
for implementation.

## Sources of truth

Read `AGENTS.md`, `CLAUDE.md`, and the relevant implementation-state files
before editing. `BACKLOG.md` is the active, cross-project queue;
`workingOn.md` is resumable state for work in progress; `DEFERRED.md` holds
parked work and permanent non-goals; `Done_Backend.md` and `Done_Frontend.md`
are durable, topic-organized worklogs. Follow `docs/README.md` if the request
touches another state document.

## Workflow

1. Classify the request: create/refine a ticket, start/resume it, record
   partial progress, park/promote it, or close it. Check all relevant state
   files for an existing ticket before creating or moving anything.
2. Keep IDs stable. Before assigning one, inspect the relevant prefix in
   `BACKLOG.md`, `DEFERRED.md`, and `Done_*.md`; do not trust a stale "next
   ID" note without checking. Use the existing category prefixes in
   `BACKLOG.md`. Never reuse a retired ID for a different subject.
3. For a new ticket, confirm it is distinct from open, deferred, and shipped
   work. Write only a concise title and actionable open scope in the
   appropriate `BACKLOG.md` category. Do not add progress, history, or
   residue there. Record dependencies or blockers only when verified.
4. On starting work, first resume the ticket's existing `workingOn.md` block
   from its exact **Next step**. If none exists, create one from that file's
   template. Keep one block per active ticket, do not edit another ticket's
   block, and update it at meaningful milestones with tested work, next
   action, decisions, evidence, and remaining residue.
5. If work is partial, keep the ticket in `BACKLOG.md` as a terse open point;
   put exact remaining scope and next action in its `workingOn.md` block.
   Do not call it done while residue remains.
6. To park unscheduled work, move its full open write-up from `BACKLOG.md`
   into the appropriate part of `DEFERRED.md`, preserving its ID. Promote
   it by moving it back to the matching backlog category. Permanent
   non-goals belong in `DEFERRED.md`, not the backlog.
7. To close a ticket, verify its scope and residue are complete. Remove it
   from `BACKLOG.md` or `DEFERRED.md`, delete its whole `workingOn.md` block,
   and file the concise "what shipped and why" narrative under the matching
   existing subsystem entry in `Done_Backend.md` or `Done_Frontend.md`.
   Extend a related entry instead of duplicating it or appending a
   chronological log.

## Guardrails

- Treat current code and tests as authoritative; do not mark work done based
  only on a plan, claim, or stale ticket text.
- Before recording a blocker as "needs a new primitive", check existing
  code and Done entries for equivalent work. When a primitive lands, check
  whether it closes or narrows other open tickets.
- For parser tickets, use the `extend-parser` workflow and measure scope;
  for card-specific authoring, route to `hand-author-card`. Keep their
  technical instructions in those skills rather than copying them here.
- Ask the user when scope, ticket identity, category, or scheduling is
  materially ambiguous. Do not invent acceptance criteria or silently
  reprioritize unrelated work.
- Do not commit unless asked. Report the ticket ID and the state files
  changed.
