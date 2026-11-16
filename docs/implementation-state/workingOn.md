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
- **Next step:** <the exact next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <where baselines, dumps and probes live>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## ENG-61 · Retire named-string and flat group selectors

- **Started / last update:** 2026-11-16 / 2026-11-16
- **Goal of this run:** (b) hand-authored `card_catalogue` entries off named strings/flat group params (owner request), then (a) one-shot effect `selector` vocabulary and the four parser residues, then (c) delete the named branches and flat tail in `group_selector_objects`.
- **Done (milestone 1, part b):** 210 hand-authored `card_catalogue` files (~235 sites) on structured selectors: ~175 static `affects` (grant_keyword, anthem, grant_mana_ability, grant_*_ability, type_change, combat_restriction, pt_set, untap, protection, ...), ~50 one-shot `selector`s whose reader goes through `group_selector_objects` (pump, tap, unblockable, combat_restriction_this_turn, ...), ~25 mass destroy/exile/gain_control moved from string `selector` to `group` (`_group_objects`). Flat `subtype`/`tokens`/`exclude_self`/`subtype_from_source` folded into the filter only where the handler reads them solely through `group_selector_objects`; other flat params stay beside the dict (applied after the structured branch). `tests/test_eng61_selector_equivalence.py` (56): 36 named strings, 13 flat combinations, 12 mass strings proven equal to their structured form on 3 boards x 2 perspectives. Suite 23,393 passed.
- **In progress:** —
- **Next step:** part (a): migrate the string-comparing readers, then their callers: `continuous.activation_prohibited` (~5697/5700/5792: `opponents_permanents`, `all_permanents`) and `enters_tapped` (~7376); mass `destroy`/`exile`/`return_to_hand` `_mass_selector_objects` so `group` honours `filter`/`exclude_created`; whitelisted one-shot selectors `_ADD_COUNTERS_SELECTORS`, `_DAMAGE_SELECTORS` (+ `selector_filter`), `goad._SELECTORS`, `phase_out`; plus the four parser residues (Alpine Moon, named_card_statics on `all_permanents`+`card_name_from_source`, emblem_statics, effect-body lock_group). Then the residue cards below, then (c) delete the named branches.
- **Decisions:** equivalence is proven per selector shape on varied real boards, not per card; entries whose reader compares the string itself stay until (a) migrates that reader.
- **Baselines / artefacts:** masked-diff baseline `scratchpad/eng60/verify921.json`.
- **Known failures:** —
- **Residue (cards still on strings):** string-comparing static layers: activation_prohibition (Disruptor Flute, Drana and Linvala, Karn the Great Creator, Petrified Hamlet, Phyrexian Revoker, Pithing Needle, The Immortal Sun), cost_reduction (Suppression Field, Tithe Taker), enters_tapped_static (Dauntless Dismantler). Mass effects with `filter`/`exclude_created`: destroy (Austere Command x2, Citywide Bust, Culling Ritual, Fell the Mighty, Martial Coup, Ruination, Steel Hellkite, The Battle of Bywater, White Sun's Twilight, Winds of Rath), exile (Chainer, Dementia Master), return_to_hand (Aetherize, Llawan, Perplexing Test x2); unmapped names `all_battles` (destroy), `artifacts_you_control` (Dispatch exile). Whitelisted one-shot selectors: add_counters `each_*` (+ Ao, 17 sites), damage `each_creature`/`each_other_creature` (7, with `selector_filter`), goad (2), phase_out (1). Legendary selectors (`legendary_creatures_you_control` 2, `nonlegendary_creatures_you_control` 1, `legendary_permanents_you_control` 1): the `legendary`/`nonlegendary` filter keys read the printed `obj.card.is_legendary` (combat.py ~1051/1055), not the layer-derived `obj.is_legendary` -- fix the filter key first (RULE 205.4 supertype changes). `enchanted_or_equipped_creatures_you_control` (1): no filter key. Tests assert old strings: Kulrath Knight, Earthshape, Acolyte of Bahamut, Dungeon Delver, Haunted One, Master Chef, Noble Heritage, Scion of Halaster, Tavern Brawler. Mass destroy/exile iteration order is now player by player (simultaneous events; watch trigger-order tests).
