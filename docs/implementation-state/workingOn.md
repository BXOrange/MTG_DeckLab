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

## PAR-285 · Object filters

- **Started / last update:** 2026-11-18 / 2026-11-18
- **Goal of this run:** shrink the `P1-C Objektfilter` package one measured slot family per milestone (one commit each).
- **Done (v970–979, each 0 lost; tests `backend/tests/test_par285_*.py`, parser -> binder -> engine on real cards):**
  M1 X-or-less stat bounds on creature targets (+5). M2 can't-block row carries target quality; `CantBlockEffect.creature_filter` (+3).
  M3 "another target X" -> `excludes_source` (+21, +5 authored). M4 sequential "another target" -> `distinct_from_others` (+4).
  M5 controller's own sacrifice of a qualified pool (+17). M6 search qualifiers legendary/nonlegendary/non<type> (+6, +3 authored).
  M7 graveyard multi-pick scope/tapped/card-type slots (+5, +1 authored). M8 graveyard single-pick subtype slot, `has_subtype` match (+33, +4 authored).
  M9 X / any-number target counts; single-type artifact/enchantment/land frames now apply `creature_filter`, `without_type` read (+12, +5 authored).
  M10 graveyard "creature or land" union; counter-spell `color_any` / `non_color` / `without_card_types` / `without_subtype` / Aura (+10).
- **In progress:** (nothing)
- **Next step:** re-run `find_fragments.py --all-cards --axes` at v979 and refresh the P1-C count, then probe and pick the largest solo slot among: dynamic mana-value bound "less than or equal to <count>" via `count_selector` (Sundering Archaic, Legacy's Allure, Grim Servant); `nonsnow land you control` (Hallowed Ground) and `nonwhite, nonblack` colour lists (Seize the Soul); "creature or legendary spell" (Icy Reception); Duskana `base power and toughness 2/2`.
- **Decisions:** milestones commit one at a time; the orchestrator runs `--full-cache` every fifth loop iteration (last: M5, M10). `combat.matches_object_filter` silently ignores unknown keys, so every new filter key needs a reader check. Hand-put per-player family is not object-filter work: filed as MEC-150.
- **Baselines / artefacts:** P1-C: v969 277/271/145, v975 234/228/113. Exports `backend/data/exports/offene-fragmente-2026-11-18-v9*-vollpool-*`.
- **Known failures:** (none)
- **Residue:**
  - Hand-put per-player family filed as MEC-150 (11 cards); out of PAR-285 scope.
  - Counter-spell leftovers: Anticognition, Molten Influence, Permission Denied, Test of Talents, Spellshift, Odds // Ends (second clause); Avoid Fate, Ring of Immortals (`that targets a permanent you control`); Get Out, Tidal Control, Gerrard and Hanna, Recommission, Geth, Captain N'ghathrod, Jolted Awake.
  - Graveyard: Salvaging Station (`noncreature artifact card ... mv 1 or less`), hand+graveyard returns/exiles (Kastral, Thran Temporal Gateway, Identity Crisis, Thought Distortion, Worldfire), `that was put there this turn` (Abyssal Harvester, Lobelia), mv bounds on exile (Sequence Engine, Tamiyo, Nahiri, Narset, Arcane Proxy).
  - Sacrifice: Ravenous Vampire (`if you don't`), Reno and Rude / Vengeful Villagers, Dreadfeast Demon / Promise of Aclazotz (`non-demon` cost), Abjure / Ultimate Nullification (additional cost), Iron Man.
  - Sequential another: Rookie Mistake, Arm the Cathars, Blue Dragon, Trick Shot, Serpentine Spike, Withdraw, Friendly Rivalry, Graceful Takedown, Tandem Takedown, Biomantic Mastery, Cruel Entertainment.
  - Plural "other" anthems (multi-subtype union 5 cards / 1 solo; keyword grants toxic/ward 5 solo).
  - Search: Hero's Uncle, Templar Knight, Grim Reminder, The Champion, In Residence, Night Dealings.
  - X-shaped: Ent-Draught Basin (`power x` exact), mass `toughness/mana value x or less` (Zero Point Ballad, Day of Black Sun, Droning Bureaucrats); Archipelagore, Reap, Back in Town, Wake the Dead, Long Rest (x target + rider).
  - Carried from PAR-284: Duskana, Cid (anthem head union). Unverified in play: Aryel X-from-tap cost; Changeling spell vs "non-Faerie" (Faerie Trickery) before binder sets `intrinsic_keywords`.
