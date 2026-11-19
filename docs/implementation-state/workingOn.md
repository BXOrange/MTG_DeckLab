# Working on — resumable state of the ticket in progress

**The working memory for a ticket that is being built right now.** It exists so that a
new session — after the prompt cache expired, a crash, an update, a context compaction —
continues exactly where the last one stopped instead of re-deriving the state from the
code, the git log and the backlog.

Rules:

- **Read this file first** when you start or resume work on any ticket. If your ticket has
  a block below, continue from its *Next step*; do not re-evaluate what it records as done.
- **One block per ticket in progress**, headed `## <TICKET-ID> · <title>`. Several sessions
  may share this working tree, so never edit another ticket's block.
- **A partly done ticket's residue lives here, not in `BACKLOG.md`.** When a run ends with
  part of the ticket still open, keep its block and record under *Residue* exactly what is
  left (card clusters, blockers, which cards each needs) plus the *Next step*; `BACKLOG.md`
  keeps only the ticket's terse open point (id, title, one-clause scope).
- **Update the block at every milestone**, not only at the end: after a sub-step is built
  and tested, after a decision, before a long-running command (full test tier, coverage
  run), before a commit. Write it so a reader with *no* conversation context can act on it.
- Keep it terse and current — replace stale lines instead of appending. Keep only
  the current resumable state; session logs belong in unversioned temporary files.
- **Commit every iteration** (each green milestone: sub-step built + tested), not only at
  ticket close; update the block first so the commit carries the current state. Stage only
  your own files (see the shared-tree note in memory), never `git stash`.
- **On closing the ticket, delete its whole block.** Durable results for shared
  engine/parser features belong in `Done_Backend.md` / `Done_Frontend.md`;
  individually modeled cards stay documented in their implementations and tests,
  not in `Done_Backend.md`. A ticket is closed only once its residue is done too.
  With no ticket in progress this file is just this header and the empty template
  — no ticket id, no log.

Block template (do not change this, copy below the line, fill in there):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done:** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <the exact next action a fresh session takes>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <where baselines, dumps and probes live>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-287 · Cross-sentence referents

- **Started / last update:** 2026-11-19 / 2026-11-19
- **Goal of this run:** milestone 1 done; continue with the damage-recipient and "that creature" event-referent groups.
- **Done:** M1 (v998): SPELL_CAST-triggered bodies chaining `counter / copy that spell` and `sacrifice ~` (`trigger_heads._counter_triggering_spell_effects`; SPELL_CAST only): +4 newly MODELED (Hesitation, Lunar Force, Double Down, Case of the Shifting Visage) +1 authored (Reflections of Littjara), 0 lost, 0 changed. Tests `tests/test_par287_triggering_spell_steps.py`.
- **In progress:** (nothing)
- **Next step:** damage-recipient group under a "deals (combat) damage to a creature" head: Mercurial Kite and Queen of Ice (`tap that creature` + next-sentence `that creature / it doesn't untap ...`), Obelisk Spider (`put a -1/-1 counter on that creature`), Sword of Kaldra / Neko-Te ("equipped creature deals damage to a creature"); reuse `target_operand: "damage_recipient"` (Kashi-Tribe Reaver row, `pump_stats.py`) and `trigger_subject` (Kaldra Compleat). Then Volo head ("doesn't share a creature type with ..."), Nullstone Gargoyle head ("first noncreature spell of a turn is cast"), Decree of Silence / Common Courtesy.
- **Decisions:** one commit per milestone; the orchestrator runs `--full-cache` every fifth loop iteration. A referent is only real if the engine resolves it to the antecedent's actual object or amount: tests use a same-type bystander as the near-miss.
- **Baselines / artefacts:** v997 scan: `P1-E Rückbezug` 380 sentences / 357 touched / 92 solo (`backend/data/exports/offene-fragmente-2026-11-19-v997-vollpool-achsen.md`). Ranking by (referent, verb), solo cards, in the scratchpad `p1e_rank.txt`.
- **Known failures:** (none recorded)
- **Residue:** P1-E solo groups left (v997): `that creature` + deals/damage-recipient 10 (Consuming Ferocity, Crash Landing, Curse of Stalked Prey, Jaya Fiery Negotiator, Mercurial Kite, Neko-Te, ...), `that creature` + untap 4 (Glacial Grasp, Loki, Kite, Neko-Te), `that player` + deals 4 (Crimson Honor Guard, Furnace Punisher, Fall of Kroog, Walker of Secret Ways), `that creature` + gets 4 (Elemental Appeal, Gahiji, Kry Shield, Subdue), `that many` 13 (Bioessence Hydra, Font of Agonies, Lonis, Phyrexian Negator/Totem, Last Stand, Varina ...), "if you do" 3 (Akuta, Act of Authority, Egon), Bounding Felidar. That-spell group still open: Volo (head), Nullstone Gargoyle (head), Common Courtesy, Decree of Silence (conditional sacrifice), Forger's Foundry (exile that spell).
