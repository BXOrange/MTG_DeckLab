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

## MEC-145 · Recorded referents of cost and effect objects

- **Started / last update:** 2026-11-20 / 2026-11-20
- **Goal of this run:** M1: last-known-information stamps (RULE 608.2h) for discard, exile (graveyard / top of library / linked exile), tap and reveal costs, mirroring the `sacrificed_cost_*` stamps, read by `continuous.count_selector` / `effect_amounts`, plus the parser binding of `where X is the <noun>'s <characteristic>`; then the effect-produced referents, the amassed Army (PAR-284 close), the PAR-285 / PAR-286 cost cards.
- **Done (M1, PARSER_VERSION 1016, not closed):** `game/cost_referents.py` + `GameObject.cost_referents` (kind -> records of mana value / power / toughness / card-type count, snapshotted as the cost moves the object, reset per payment, plain dicts so clone/undo keep them); stamped by activation costs (discard incl. random, exile from graveyard / top of library / Food Chain creature exile, tap others, sacrifice) and spell additional costs (discard, exile from graveyard, tap others, sacrifice, sacrifice count); read by the `cost_referent_<kind>_<stat>` count-selector family. Parser: `count_phrase.parse_cost_referent_term`, `gate._cost_referents_ok` (cost text / `additional_cost` must hold the verb), `effect_body.respell_effect_produced_referents` (an earlier instruction of the same body -> existing `this_way_sum` pool), `overrides_and_amounts._THIS_WAY_SINGLE_RE`, tap cost "other than ~". Claimed + engine-executed incl. the LKI case (`tests/test_mec145_cost_referents.py`, 21 tests): Volrath the Fallen, Necropolis, Impelled Giant (tapped creature destroyed before resolution), Keldon Battlewagon, Slumbering Tora, Flesh // Blood, Ruinous Intrusion (exiled artifact MV), Spellbound Dragon (discard shape), plus Corpse Lunge, Dread Defiler, Mercurial Chemister, Pyromancy (random discard), Ninja's Blades (granted trigger, executed), Shadowheart, Dark Justiciar ("that creature's power" after a sacrifice cost, respelled onto the existing `sacrificed_cost_power` by `activation_clauses.name_sacrificed_cost_creature`, refused when the effect has its own target). Orchestrator review: a spell copy now carries `cost_referents` (`copies_mixin._SPELL_COPY_CHOICES`, RULE 707.10; test `test_a_copy_of_the_spell_keeps_the_exiled_card_referent`). Tests: 24 in `tests/test_mec145_cost_referents.py`. Probe diff vs 1015 HEAD worktree: +14 newly covered, 0 regressed. The `revealed` kind exists in `cost_referents` but no cost records it and the parser does not spell it ("the revealed card" has its own `REVEALED` reading, PAR-284 test guards it).
- **In progress:** (none)
- **Next step:** first (0) per-activation referents: activated-ability records live on the source permanent and `reset_referents` clears them at each payment, so a second activation of Volrath / Keldon Battlewagon / Necropolis while the first is still on the stack overwrites the first's records (RULE 608.2h: each ability keeps its own cost LKI; the old `sacrificed_cost_*` stamps share the flaw). Snapshot the records onto the `StackItem` at activation and read them from the resolving item, with a two-activations-on-the-stack test. Then pick the residue groups in order: (1) card-type count (`characteristic` `card_types` for `this_way_sum` / a `cost_referent` effect-side reader) for Mount Velus Manticore (reflexive "when you do" after "you may discard"); (2) reveal additional cost with a chosen hand card (Disaster Radius, Induce Despair: `reveal_from_hand` is a creature-type word and is only a payability check, no pick/record) and "exile an instant or sorcery card from your graveyard" additional cost (Draconic Intervention; also needs its "would die this turn, exile it instead" rider); (3) linked-exile referent (Redemptor Dreadnought, Bishop of Binding, Drach'Nyen: `state.track_exiled_with` already records the cards, needs a `linked_exile_*` selector reading them); (4) returned-from-graveyard referent (Foul Renewal: the `returned` pool is only the battlefield bounce); (5) sacrificed-set aggregate (Sword of the Ages total power, Vicious Betrayal, Emrakul's Evangel count: "any number of" sacrifice costs; the records already sum, the cost parse and `this_way` spelling for cost-side "sacrificed this way" are missing); (6) Minsc & Boo ("-2: Sacrifice a creature. When you do ... that creature's power" reflexive after loyalty cost); (7) PAR-284 amassed Army (Foray of Orcs has no spec at all, Surrounded by Orcs / Goblin Plate Mail, Grishnakh: `AmassEffect` already appends the Army to `context.created_objects`, `costs_mana_limits._AMASSED_ARMY_POSSESSIVE_RE` handles only the reflexive form); (8) PAR-285 sacrificed-permanent cards (Fatal Grudge shares-type, Nahiri's Sacrifice X = sacrificed MV with an `x` in the cost word, etc.): re-probe each, the `sacrificed` records are in place.
- **Decisions:** One generic record structure on the holder (spell or ability source), summed per kind, instead of one stamp per card; effect-produced referents reuse the existing "<verb>ed this way" pools (`this_way_sum`) rather than a second structure, the parser picks by whether an earlier instruction of the same body produced the object, otherwise the cost reading is checked against the cost at the gate (fail closed). The old `sacrificed_cost_*` scalar stamps stay for their existing readers; the new `sacrificed` records are additive.
- **Baselines / artefacts:** PARSER_VERSION 1015 at start, 1016 now (lock re-pinned). Baseline snapshot of HEAD parse via a HEAD worktree (scratchpad).
- **Known failures:** none. Plain suite 25,846 passed / 505 skipped; `--full-cache` 26,346 passed / 4 skipped (2026-11-20, M1 tree).
- **Residue:** Venom: the cached "Venom" is an already-MODELED Aura and "Eddie Brock // Venom, Lethal Protector" has no referent clause; the backlog name is probably a stale pick, drop it from the list. Shadowheart is done (Dark Justiciar). Phyrexian Devourer: its cost reading now parses; the other line "When this creature's power is 7 or greater, sacrifice it." (state trigger) is unclaimed. Disaster Radius, Induce Despair, Draconic Intervention, Redemptor Dreadnought, Bishop of Binding, Mount Velus Manticore, Foul Renewal, Minsc & Boo, Sword of the Ages, Vicious Betrayal, PAR-284 / 285 / 286 cards: see Next step for the per-group blocker.
