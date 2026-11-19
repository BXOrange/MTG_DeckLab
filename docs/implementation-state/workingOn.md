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
- **Goal of this run:** milestones 1-5 done (v1002); the remaining P1-E solo cards are classified in the closure doc, ready to close.
- **Done:** M1 (v998): SPELL_CAST-triggered bodies chaining `counter / copy that spell` and `sacrifice ~` (`trigger_heads._counter_triggering_spell_effects`; SPELL_CAST only): +4 newly MODELED (Hesitation, Lunar Force, Double Down, Case of the Shifting Visage) +1 authored (Reflections of Littjara), 0 lost, 0 changed. Tests `tests/test_par287_triggering_spell_steps.py`.
  M2 (v999): `that creature` / `that player` under a damage head (`line_rows_abilities.recipient_body` + `look_at_hand{damaged_player}`): +5 newly MODELED (Mercurial Kite, Queen of Ice, Obelisk Spider, Sword of Kaldra, Walker of Secret Ways), 0 authored, 0 lost, 0 changed. Tests `tests/test_par287_damage_recipient_referents.py`.
  M3 (v1000): damage-party referents corrected (Toxin Sliver, Zagras, Hooded Blightfang: recipient not dealer; Elder Mastery, Specter's Shroud, Sword of Body and Mind: damaged player not host controller; Neko-Te claim fixed) + Volo, Nullstone Gargoyle, Decree of Silence, Phyrexian Negator / Totem, Varina: +6 newly MODELED, 0 authored, 0 lost, 6 corrected. Tests `test_par287_damage_party_referents.py`, `test_par287_referent_heads_m3.py`.
  M4 (v1001): bounded `discards X cards` row (Mind Twist, Mind Shatter, Mind Burst, Greel, Arcane Omens, Cabal Shrine, Tormented Thoughts), Felothar's "its power" = the sacrificed creature, Egon "if you can't" (`seq` with empty payoff + else), Act of Authority (`previous_subject_controller`), Bounding Felidar (`counter_recipients_since_mark`), Gideon pair (`animates_source`), nested seq keeps the milled pool: +20 newly MODELED (13 targets + Contested War Zone, Inventive Iteration, Momentous Fall, Patient Naturalist, Roots of Wisdom, Temp of the Damned, Temporal Conqueror; Felothar and Temporal Conqueror also hand-authored), 0 lost, 0 changed. Tests `test_par287_m4_referents.py`.
  M5 (v1002): `that many` for counter-put events (Bioessence Hydra, Lonis), player-scoped group handoff for `PumpEffect.group_player` (Great Oak Guardian, Trystan's Command), mill referent transparency, `+0/+X` row (Kry Shield, Subdue), `their hand` graveyard returns (Four Advocates, Kitsune Loreweaver), "If C, you may <cost>. If you do, <effect>" pairs (Take Out the Trash, Chandra's Defeat, Taborax), "that opponent" under opponent-damage heads (Zhang Liao, Fungal Shambler), Drown in Filth, Grave Strength, Glacial Grasp: +21 newly MODELED, 0 authored, 0 lost, 0 changed. Tests `tests/test_par287_m5_referents.py` (45).
- **In progress:** (nothing)
- **Next step:** close PAR-287 (delete the backlog entry, extend Done_Backend). Paste the singleton rows and cluster tickets from `<scratchpad>/par287-closure-final.md` (clusters A-E, ready-to-paste `| Card | Gap | Notes |` rows, proposed MEC lines).
- **Decisions:** one commit per milestone; the orchestrator runs `--full-cache` every fifth loop iteration. A referent is only real if the engine resolves it to the antecedent's actual object or amount: tests use a same-type bystander as the near-miss.
- **Baselines / artefacts:** v997 scan: `P1-E Rückbezug` 380 sentences / 357 touched / 92 solo (`backend/data/exports/offene-fragmente-2026-11-19-v997-vollpool-achsen.md`). Ranking by (referent, verb), solo cards, in the scratchpad `p1e_rank.txt`. v1002 (final tree): `P1-E Rückbezug` 337 / 318 / 60 (`...-v1002-vollpool-achsen.md`).
- **Known failures:** (none recorded)
- **Residue:** 60 solo cards, all classified in `<scratchpad>/par287-closure-final.md` (clusters A-E, singletons, owned-elsewhere, unsupported). M5 skipped: Abigale (the engine strips keyword counters from an object that loses all abilities, no layer-6 timestamps), the ability-word rider merge (Delirium / Fateful hour / Spell mastery paragraphs: changes 8 MODELED specs for 4 new cards), a generic "that opponent" beyond damage heads.
