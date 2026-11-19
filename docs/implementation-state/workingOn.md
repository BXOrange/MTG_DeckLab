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
- **Goal of this run:** milestones 1-2 done; continue with the remaining "that creature" / "that many" groups.
- **Done:** M1 (v998): SPELL_CAST-triggered bodies chaining `counter / copy that spell` and `sacrifice ~` (`trigger_heads._counter_triggering_spell_effects`; SPELL_CAST only): +4 newly MODELED (Hesitation, Lunar Force, Double Down, Case of the Shifting Visage) +1 authored (Reflections of Littjara), 0 lost, 0 changed. Tests `tests/test_par287_triggering_spell_steps.py`.
  M2 (v999): `that creature` / `that player` under a damage head (`line_rows_abilities.recipient_body` + `look_at_hand{damaged_player}`): +5 newly MODELED (Mercurial Kite, Queen of Ice, Obelisk Spider, Sword of Kaldra, Walker of Secret Ways), 0 authored, 0 lost, 0 changed. Tests `tests/test_par287_damage_recipient_referents.py`.
  M3 (v1000): damage-party referents corrected (Toxin Sliver, Zagras, Hooded Blightfang: recipient not dealer; Elder Mastery, Specter's Shroud, Sword of Body and Mind: damaged player not host controller; Neko-Te claim fixed) + Volo, Nullstone Gargoyle, Decree of Silence, Phyrexian Negator / Totem, Varina: +6 newly MODELED, 0 authored, 0 lost, 6 corrected. Tests `test_par287_damage_party_referents.py`, `test_par287_referent_heads_m3.py`.
- **In progress:** (nothing)
- **Next step:** remaining `that many`: Bioessence Hydra, Lonis Genetics Expert (counter-put events), Font of Agonies (needs a pay-life event), Last Stand (back-reference count); "if you do" (3); a bounded `discard X cards` row that does not misbind Felothar's "cards equal to its power" (would also claim Mind Twist, Mind Shatter, Mind Burst, Greel, Arcane Omens, Cabal Shrine, Tormented Thoughts).
- **Decisions:** one commit per milestone; the orchestrator runs `--full-cache` every fifth loop iteration. A referent is only real if the engine resolves it to the antecedent's actual object or amount: tests use a same-type bystander as the near-miss.
- **Baselines / artefacts:** v997 scan: `P1-E Rückbezug` 380 sentences / 357 touched / 92 solo (`backend/data/exports/offene-fragmente-2026-11-19-v997-vollpool-achsen.md`). Ranking by (referent, verb), solo cards, in the scratchpad `p1e_rank.txt`.
- **Known failures:** (none recorded)
- **Residue:** P1-E solo groups left: `that creature` + untap/gets (Glacial Grasp: its-controller-mills sentence between; Loki; Kry Shield / Subdue: `+0/+X where X is its mana value`; Elemental Appeal kicker rider; Gahiji head "attacks 1 of your opponents or a planeswalker an opponent controls"; Curse of Stalked Prey head "deals combat damage to enchanted player"), damage-head siblings needing new primitives: Neko-Te (no-untap "for as long as ~ remains on the battlefield"), Bellowing Fiend / Death Charmer / Plague Fiend / Soul Charmer ("that creature's controller", "unless pays"), Creepy Doll (coin flip), Flayed Nim, Permeating Mass, Venomous Fangs / Charisma ("the other creature"); `that player` + deals: Crimson Honor Guard / Furnace Punisher ("unless they control" on each-player step), Fall of Kroog (target opponent). `that many` 13, "if you do" 3, Bounding Felidar. Pre-existing doubt: a GROUP damage head ("a creature you control deals damage to a creature") reads "that creature" as the dealer (`__group_subject__`), and Neko-Te's "equipped creature deals damage to a player, that player loses 1 life" claims `player: {of: attached, as: controller}` (the host's controller, not the damaged player): both need a look. That-spell group still open: Volo, Nullstone Gargoyle, Common Courtesy, Decree of Silence, Forger's Foundry.
  M3 skipped: Common Courtesy (table-talk condition, not a game event); Erayo (fourth spell, flip).
