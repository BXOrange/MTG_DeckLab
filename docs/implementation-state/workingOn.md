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
- **Done (v970–983, each 0 lost; tests `backend/tests/test_par285_*.py`, parser -> binder -> engine on real cards):**
  M1 X-or-less stat bounds on creature targets (+5). M2 can't-block row carries target quality; `CantBlockEffect.creature_filter` (+3).
  M3 "another target X" -> `excludes_source` (+21, +5 authored). M4 sequential "another target" -> `distinct_from_others` (+4).
  M5 controller's own sacrifice of a qualified pool (+17). M6 search qualifiers legendary/nonlegendary/non<type> (+6, +3 authored).
  M7 graveyard multi-pick scope/tapped/card-type slots (+5, +1 authored). M8 graveyard single-pick subtype slot, `has_subtype` match (+33, +4 authored).
  M9 X / any-number target counts; single-type artifact/enchantment/land frames now apply `creature_filter`, `without_type` read (+12, +5 authored).
  M10 graveyard "creature or land" union; counter-spell `color_any` / `non_color` / `without_card_types` / `without_subtype` / Aura (+10).
  M11 creature stat-bound slots: measured bound `stat_count_bound` (life total, counters on ~, hand/graveyard/land counts), "power or toughness N", "total power and toughness N"; targets and mass `for_each` share `combat.matches_object_filter` (+8, 0 authored).
  M12 stacked negations: comma list "nonwhite, nonblack" on targets, `nonsnow` / `noncommander` / `nonblocking` / "non-outlaw" kinds (fixes silent bogus subtype filters), mass "<adj> creatures can't block this turn" row (+8, 0 authored; `test_par285_negation_lists.py`).
  M13 library search bounded by a measured mana value (`search_mv_measured` row -> `mana_value_from` count_selector; devotion, zone counts, counters on ~; +3, 0 authored; `test_par285_measured_mv_search.py`).
  M14 (v983) "other <subtype|attacking|blocking|modified> creatures [you control]" and "other <A> and <Bs>" as a pump group subject (`effect_rows.shared._GROUP`; +6: Faerie Noble, Phyrexian Driver, Orc General, Bolg, Qala, Marton; 0 authored; `test_par285_other_group_pumps.py`).
  M15 (v984) "<adj> permanents <scope>" / "attacking <quality> creatures you control" as grant/loss group subjects (`shared._GROUP`; +2: Exterminatus, War Machine Avenging Arsenal; Dora Milaje Elite parses its sacrifice ability but stays on the named Vibranium token = PAR-297; `test_par285_qualified_permanent_groups.py`).
  M15 fix: `_search_mv_measured` refuses the unqualified lands bound (`_SEARCH_MV_LANDS_QUALIFIER_RE.fullmatch`), fixing the M13 shadowing failure (Beseech spec unchanged, no IR change, 984 kept; `--full-cache` test_par169_handler_shadowing 5 passed).
  M16 (v985) graveyard pick quality / mana-value-bound slots: shared `_GRAVEYARD_MANA_VALUE_SLOT` (N or less, exact N, X, X or less, <= / strict < ~'s power = new `source_power_less_than`), `qual` (legendary, multicolored, legendary-or-<subtype> `any_of`), single colour on exile, type words `instant` / `noncreature artifact`, `ExileEffect.exact_mana_value` (+12: Abiding Grace, Arcane Proxy, Narset Enlightened Exile, Nashi Moon's Legacy, Nucklavee, Obscura Charm, Reborn Hope, Salvaging Station, Scrivener, Sequence Engine, Mirari Conjecture, Toshiro Umezawa; +2 authored; `test_par285_graveyard_quality_bound.py`).
  M17 (v986) G: "exile up to N/X other target creatures from the battlefield and/or creature cards from graveyards" (`creature_or_any_graveyard_creature`), linked-pool return rows, Training (RULE 702.149a) as a real ATTACKS trigger + `TRAINS` event, disguise `{X}` turn-face-up (Angel of Serenity, Aurelia's Vindicator, Savior of Ollenbock). E: qualified additional-cost sacrifice word (legendary/nonland/power>=N/modified creature; `spec.additional_cost_sacrifice_word_ok`; Lethal Throwdown, Abjure; Rite of Oblivion/Natural Order also parse). C: `TimeCountersEffect` + suspended-card target kinds (Shivan Sand-Mage, Timebender, Timecrafting, Dust of Moments, Fury Charm). Full-pool diff 0 lost, 12 newly MODELED, 0 changed. Tests `test_par285_battlefield_or_graveyard_pool.py`, `_qualified_sacrifice_cost.py`, `_time_counters.py`.
- **In progress:** closure prep done; ticket ready for the orchestrator to close (no further P1-C milestone; remaining class (i) cards each have a second open clause owned elsewhere).
- **Next step:** orchestrator closes PAR-285 (delete block, extend Done_Backend, paste singleton rows and per-ticket hand-over lines below). Remaining E blockers: Fatal Grudge (shares-a-type edict), Ultimate Nullification (exile all creatures and graveyards), Savage Order (search + indestructible, PAR-292), Louisoix's Sacrifice (stack, PAR-308), Nahiri's Sacrifice (X := sacrificed mana value).
- **Decisions:** milestones commit one at a time; the orchestrator runs `--full-cache` every fifth loop iteration (last: M5, M10). `combat.matches_object_filter` silently ignores unknown keys, so every new filter key needs a reader check. Hand-put per-player family is not object-filter work: filed as MEC-150.
- **Baselines / artefacts:** P1-C: v982 198 sentences / 195 touched / 182 only (export in scratch, not committed); v983 not re-measured (expected 189 touched); v969 277/271/145, v975 234/228/113, v979 217/212/99, v980 208/204/92, v981 202/199/88. Exports `backend/data/exports/offene-fragmente-2026-11-18-v9*-vollpool-*`.
- **Known failures:** (none)
- **Residue:** P1-C at v986 (find_fragments --all-cards): 167 cards / 170 sentences (v982: 195). Final classes: (i) 10 still blocked (Dual Nature, Eye of Singularity, Faces of the Past, Kaervek, Lara Croft, Legion's End, Martyr's Bond, Nahiri's Sacrifice, Nahiri the Unforgiving, Spreading Plague: same-name / shares-quality referents and cost X := sacrificed MV); (ii) 41 singleton candidates (rows ready in the orchestrator report); (iii) 89 owned elsewhere (PAR-303 20, PAR-297 17, MEC-145/PAR-287 17, PAR-292 11, PAR-298 9, PAR-308 6, PAR-300 4, PAR-286 3, MEC-150 2); (iv) 27 mis-scanned (PAR-293 Charakteristik 26, GEPARKT Un-Sets 1: The Fearsome Flock).
