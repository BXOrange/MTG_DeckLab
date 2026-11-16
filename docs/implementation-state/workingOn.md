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
- **Done (built + tested, 23 new tests in test_par249_token_names_creating_card.py):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** milestone 3: plural graveyard exile ("exile up to N target <type> cards from <graveyard>": Kenriths' Royal Funeral, Skullsnatcher, Boneyard Parley) and exile-with-counters riders (Doom's Time Platform, The Animus, Tasha, Tinybones, Lara Croft); then edicts, Stern Scolding, `choose_targets` mana value. Cluster (a) "exile all [quality] cards from <hand/graveyard>" needs a new effect for ~3 solo cards (Identity Crisis, Thought Distortion): owner decision whether to build it, asked in the loop report. Dynamic search qualities and the ~66 condition/amount sentences go to PAR-283/284 at close.
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** scratchpad par281/: maskdump.py (per-card spec hash with provenance version masked; plain specdump.py hashes include the version and show every card changed across a bump). Verified: v913->914 +10/0 lost/0 changed, v914->915 +17/0/0; m915.json is the baseline for milestone 3.
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-281 · Offer filter slots on every row

- **Started / last update:** 2026-11-16 / 2026-11-16
- **Goal of this run:** whole ticket: one ordered, fail-closed peeler step around `handlers.match_clause` that strips `with <quality>` / `from <zone>` filter slots rows already read, so the ~99 known-good-filler sentences claim (RULE 601.2c respected).
- **Done:** milestone 1: `catalogue/filter_slots.py` search carrier (10 cards, v914). Milestone 2 (v915): `_SLOTS` table (pattern + interpreter + carrier types): (d) "with <N> <kind> counter(s) on it" after a return to the battlefield -> `extra_counters` on `return_from_graveyard`/`return_self_to_battlefield` (existing reader, RULE 614.1c); (c) "from <type|colorless> source" on `counter_ability`/`copy_target_ability` -> new param `source_filter` -> `TargetSpec.stack_source_filter` + `targeting.stack_source_matches` (announcement and resolution, RULE 113.7a; `stack.py`, `registry.py`); (b-lite) graveyard type words `nonland`/`historic`/`legendary creature` (`shared.GRAVEYARD_TYPE_WORD`, `targeting._GRAVEYARD_TYPE_FILTERS`). Spec diff v914 -> v915: 17 gained, 0 lost, 0 changed. Tests in `tests/test_par281_filter_slots.py` (33) plus `test_par191` expectation updated. Gains: Rust, Brown Ouphe, Abstruse Archaic, Echo, Scientist Supreme, Tawnos, Weaver of Harmony (source filter); Makeshift Mannequin, Charnel Serenade, Thunderbolts Conspiracy, Unstoppable Slasher, Heart-Shaped Herb (entry counters); Rona, Abstergo Entertainment, Layla Hassan, Lychguard, Samwise Gamgee (graveyard words).
- **In progress:** nothing; PARSER_VERSION 915 + history + lock done.
- **Next step:** milestone 3: plural graveyard exile ("exile up to N target <type> cards from <graveyard>": Kenriths' Royal Funeral, Skullsnatcher, Boneyard Parley) and exile-with-counters riders (Doom's Time Platform, The Animus, Tasha, Tinybones, Lara Croft); then edicts, Stern Scolding, `choose_targets` mana value. Cluster (a) "exile all [quality] cards from <hand/graveyard>" needs a new effect for ~3 solo cards (Identity Crisis, Thought Distortion): owner decision whether to build it, asked in the loop report. Dynamic search qualities and the ~66 condition/amount sentences go to PAR-283/284 at close.
- **Decisions:** pytest `--full-cache` tier not run per ticket (user instruction); full-pool spec diff with zero lost cards is still the acceptance check.
- **Baselines / artefacts:** scratchpad par281/: maskdump.py (per-card spec hash with provenance version masked; plain specdump.py hashes include the version and show every card changed across a bump). Verified: v913->914 +10/0 lost/0 changed, v914->915 +17/0/0; m915.json is the baseline for milestone 3.
- **Known failures:** -
- **Residue:** the 99 "slot" sentences are not one gap: a quality is only claimable where an engine reader exists for it. Carried now: library search (10), entry counters, ability source filter, graveyard type words (17 more). No reader yet (each is its own engine/param ticket, peel must stay refused): edict sacrifice filters (Clip Wings, Run Afoul, Exile into Darkness, Pick Your Poison), `counter_ability`/`copy_target_ability` "from another legendary source that's not a commander" (Peregrine Dynamo) and "unless pays" riders (Ayesha), "exile all cards from <hand/graveyard>" (12), "exile/return ... cards from graveyard" with counters/legendary/historic (plural/with-counter riders remain), `counter` spell power/toughness filter (Stern Scolding), two-kind entry counters (Perennation), "an additional" counters (Grave Betrayal, Pyrrhic Revival), "this card ... to the battlefield" rows (Winter Soldier, Gallia), `choose_targets` mana-value filters (3), dynamic search qualities ("same name as", "mana value equal to ...": 9). ~66 condition/amount-axis sentences were not touched: their slot gap is per-row, not a shared peel.
