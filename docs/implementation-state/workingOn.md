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

## PAR-289 · Continuous statics

- **Started / last update:** 2026-11-19 / 2026-11-19
- **Goal of this run:** sub-cluster `P2 Statische Dauereffekte` by slot and build the largest clean sub-clusters milestone by milestone.
- **Done:** M1 step 1: ranking written to `backend/data/exports/par289_rank-v1003.md` (as-long-as split: 92 sentences cond-missing/body-ok, 59 cond-ok/body-missing; top buildable sub-clusters with existing engine kinds: aura `enchanted creature loses all abilities and is a X with base P/T` 12 solo, `enchanted land is a <basic>` 7, `otherwise` aura pairs 12, condition phrases (dungeon/entered/another entered/no opponent controls/gy card) ~13, `descend N —` label 4).
- **In progress:** M2 built (v1005), awaiting orchestrator close-out (full-suite + par169 shadowing in the hand-back).
- **M1 built (v1004):** descend label; condition phrases (dungeon, entered this turn, another creature entered, no opponent controls, any player controls, card in your graveyard, opponent poisoned); host-pronoun `of: attached` fix; `conditional_otherwise` pair row; new `static_rows/rows_attached_transform.py` (enchanted land basic type; loses-all-abilities + type + base P/T). Spec diff vs 1003: +61 newly MODELED, +2 authored-now-MODELED, 0 lost, 0 changed. Tests `backend/tests/test_par289_continuous_statics.py` (80).
- **M2 built (v1005):** F1 counter groups (`each [other] <creature|permanent|type> [you control] with a <counter> counter on it has <kw>`); `rows_group_subjects` ("each creature that's a <types> gets/has", "other legendary permanents you control have"); host/self conditions (isn't attacking or blocking, life >= starting, you control enchanted creature, host legendary / not legendary / a or b); host-pronoun rewrite sees through any/all/not, "it's" contraction, Otherwise half names the host (fixed Aura-as-subject bug); A3 in `rows_attached_transform` (creature types + base P/T, card-type replacement, colourless type + granted ability + ability loss, legendary, enchanted permanent base P/T) and self "has <kw> and is a <type> in addition to its other types"; engine fix: kindless counter total no longer double counts +1/+1 (`static_conditions._counter_count`). Spec diff vs 1004: +32 newly MODELED, +3 authored-now-MODELED, 0 lost, 7 changed (all still partly-claimed cards, each executed). Tests `backend/tests/test_par289_m2_statics.py` (79).
- **v1004 scan (P2 Statische Dauereffekte):** 755 sentences / 717 touched / 436 solo (was 808 / 769 / 476 at v1003); exports `backend/data/exports/offene-fragmente-2026-11-19-v1004-vollpool-*`.
- **Next step (M3):** re-scan at v1005, then rank the remainder: self conditions still open (counter-placed-this-turn kinds are kind-blind, see Residue; "it hasn't dealt damage yet", "it's modified", "~ is renowned", speed, "you control exactly N creatures ... that creature"), the quoted-ability tail of Aura statements (Minimus Containment needs a `{T}, sacrifice ~: add one mana of any color` grant), parametric keyword grants to groups (frenzy/absorb/poisonous/toxic/outlast need a grant param shape: proposed ENG-66 in Residue), coordinated lists ("goblins you control and elementals you control", "other treefolk and forests you control"; note parse_scope tags a land subtype as a creature subtype, a latent bug) and "each X card in your graveyard has <kw>" (zone-aware grant). Old M2 plan was: re-run find_fragments `--all-cards --axes` at v1004, then build the next sub-clusters from `backend/data/exports/par289_rank-v1003.md` (F1 "each other creature you control with a counter has <kw>", D6/D7 condition kinds, G1 remaining self conditions such as "it isn't attacking or blocking", "another creature you control with..."; Mishra's Domination cond "you control enchanted creature").
- **Decisions:** one commit per milestone; the orchestrator runs `--full-cache` every fifth loop iteration and before close. A static is only modeled if the engine applies it in the right layer (RULE 613) on the real card, stops applying when its condition ends, and does not affect a same-type bystander outside its subject.
- **Baselines / artefacts:** v1003 scan: `P2 Statische Dauereffekte` 808 sentences / 769 touched / 476 solo (`backend/data/exports/offene-fragmente-2026-11-19-v1003-vollpool-achsen.md`, `-gruppen.md`, `-zuordnung.jsonl`).
- **Known failures:** (none recorded)
- **Residue:** proposed (engine, 3+ cards each): ENG-66 group grant of parametric keywords (`frenzy 1`, `absorb 1`, `poisonous N`, `toxic 1`, `outlast {cost}`, `fabricate 1`, `exploit`, `crew 1`, `annihilator 1`; ~11 cards: Frenzy/Lymph/Virulent/Slivdrazi/Enduring Sliver, Hish, Karumonix, Cayth, Colonel Autumn, Astor, Arcus Acolyte) -- `flag_keywords` is FLAG-shape only; MEC-158 kind-aware `counter_put_this_turn` condition (Sigardian Paladin, Beast Erudite Aerialist, Kid Loki). M2: Ray of Frost / Animate Artifact (bare "enchanted creature loses all abilities" is deliberately out of scope per test_par257), Retro-Mutation and Spider-Man No More (second sentence "It can't attack and loses all abilities"/"It has defender and loses all other abilities"), Gift of the Deity, Minimus Containment, Planeswalkerificate, Sigardian Paladin / Beast, Erudite Aerialist (counter-placed conditions do not carry the counter kind: see MEC-158 above), Nightmare Moon (other clauses). Earlier:  proposed MEC (needs engine, 3+ cards each): `players play with their hands revealed` (7 cards, no reveal-hand flag), `it's modified` / `it hasn't dealt damage yet` / `life total <= half starting life` condition kinds (4 / 3 / 3 cards); Armament of Nyx (prevention half cannot share a static spec). Not claimed: Burden of Proof, Deep Freeze, Honest Work, Witness Protection.
