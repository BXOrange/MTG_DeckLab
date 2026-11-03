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
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## REL-1 · Pin backend dependencies with hashes (formerly BUG-45b)

- **Started / last update:** 2026-11-02 / 2026-11-02
- **Goal of this run:** (a) LLM `base_url` SSRF guard and (c) bug reports for a multiplayer session only from a seat of that table with the lobby secret. (b) is not part of this run (see Residue).
- **Done (built + tested):** (c) `api/bug_reports.py` `_require_seat_at_table` + `player_id` body field + `X-Player-Secret`; `bugReport.js` sends identity; tests in test_api_multiplayer.py (`TestBugReportTableAccess`) and test_api_solo.py; BUG_REPORTS.md note. Full suite 18242 passed, 489 skipped. Browser check done. (a) moot, see Decisions.
- **In progress:** — (parked on the user decision below; (a) and (c) are closed and filed in Done_Backend.md)
- **Next step:** user picks the lock tool and whether `setup/install.py` installs from the lock (see Residue); then generate the lock per that choice and test an install from it, including the offline wheelhouse path.
- **Decisions:** (a) no code exists: the LLM integration (api/llm.py, llm_client.py, llm_settings.py) was removed in cb09a584, so there is no `base_url` to guard; nothing built. Stale git-ignored `backend/data/llm_settings.json` still holds an API key (user may delete). (c) non-seated/observer/unknown/lost-table -> 403 (not a stateless report); only MULTIPLAYER non-solo sessions are gated.
- **Baselines / artefacts:** full suite at 55639117: 18235 passed, 489 skipped.
- **Known failures (corrected; final full-cache recheck pending):** —
- **Residue:** (b) needs a user decision, do not implement unasked: hash pins with `--require-hashes` must cover the full transitive closure for every platform/Python the project installs on (macOS `venv`, Windows `venv_win`, offline wheelhouse from `--download-wheels`). A `pip freeze` from this Mac would pin platform-only packages (e.g. `uvloop` via `uvicorn[standard]`) and break Windows installs. Open question for the user: which lock tool (pip-tools `pip-compile --generate-hashes` per platform, or `uv pip compile --universal`), and whether `setup/install.py` switches to the lock file.

## PAR-225 · Untargeted returns of controlled permanents

- **Started / last update:** 2026-11-03 / 2026-11-03 10:15
- **Goal of this run:** compose controller-chosen (untargeted) returns of controlled permanents through the shared object grammar and existing `return_to_hand` / `choose_objects` primitives: resolving ETB/upkeep choices, additional return costs, sacrifice-unless-return branches; preserve quantity, filters, self eligibility, payment timing.
- **Done (built + tested):** PARSER_VERSION 820. Rows in `effect_rows/tap_return_zones.py`: `controlled_return` (one controller pick, `choose_objects` action `return_to_hand`, `exclude_self` for "another", filter whitelist), `controlled_return_up_to` (optional multi-pick), `sacrifice_unless_return` (optional pick, `else_effects` = `sacrifice_self`); `_RETURN_GROUP_RE` accepts "their owner's hand" (return all X you control). Additional cost `return_pick` (spec.py validation, segmenter `_ADDITIONAL_COST_RETURN_RE`, `ActivationCost.return_pick`, casting_mixin `_cast_return_selection`/can-pay/pay, legal_actions `sacrifice_count_cost` with `verb: "return"`, gameBoardView label). Tests `backend/tests/test_par225_controlled_returns.py` (33).
- **In progress:** — (built, targeted tests green; final `--full-cache` run deferred by the user until all PAR tickets are done)
- **Next step:** after PAR-226..228: run `--full-cache` + `coverage_report.py`, sync the four coverage locations (CLAUDE.md, PARSER_LONG_TAIL.md, status.de/en.js), then decide close vs. residue (count-N sacrifice-unless-return and "return X Swamps" are in-scope residue).
- **Decisions:** untargeted returns use `choose_objects` (not a RULE 115 target); additional-cost pick reuses the cast action's `sacrifice_choices` + `sacrifice_count_cost` picker (flagged `verb: "return"`) instead of a new API field; count-N sacrifice-unless-return (2 forests, 3 basic lands) and "return X Swamps" stay unclaimed (an optional multi-pick cannot express all-or-nothing / X).
- **Baselines / artefacts:** PARSER_VERSION 820; spec diff v819→v820: +61 newly modeled, 0 lost, 18 changed (bounce lands etc. now untargeted pick, rules fix). v819 discovery 2026-11-03 (78 touched cards by the probe regex); calibration Shrieking Drake, Kor Skyfisher, Familiar's Ruse, Crosis's Catacombs.
- **Known failures (corrected; final full-cache recheck pending):** `test_par169_handler_shadowing` fixed via `fallback_for=("controlled_return",)` on `return_to_hand`; worker full suite 18340 passed / 489 skipped before that edit; orchestrator targeted rerun (par225, wave3, tests/parser, additional_costs) 457 passed.
- **Residue:** "any number of X ... returned this way" (3), "you may return X. If you do ..." (4), count-N sacrifice-unless-return (2-3), "unless you compliment" (1), "can't attack unless you return" (1), "up to 1 other target" ETB with token rider (1), Arid Archway surveil rider (1), Cruel "return X swamps" (1), alt-cost "return an Island rather than pay" (1), "discard a card unless you return a land" (1).

## PAR-226 · Flash permissions over shared spell filters

- **Started / last update:** 2026-11-03 / 2026-11-03
- **Goal of this run:** compose standing, conditional and temporary "cast/play ... as though ... had flash" forms through existing `flash_permission`, `conditional_flash` and temporary timing permissions; retain spell filters, player/zone scope, conditions and duration.
- **Done (built + tested):** PARSER_VERSION 821. Standing filter union (types/subtypes/historic/colorless/colour creature) + `any_player` on `flash_permission` (`static_handlers._flash_permission_filter`, `continuous.has_standing_flash_permission`, registry); `conditional_flash` keys `active_if` (static-condition dict) and `targets_a_permanent_you_control` (spec/condition_query/segmenter `_line_conditional_flash_board_state`); one-shot `grant_flash_next_spell` row (`next_only`). Tests `backend/tests/test_par226_flash_permissions.py` (10 pass). Spec diff v820->v821: +32 newly modeled, 0 lost, 1 changed (Colossal Rattlewurm: inert battlefield `grant_keyword flash` -> spell-level `conditional_flash`).
- **In progress:** nothing. Plain suite 18348 passed / 489 skipped after pinning the new row orders (handler_row_order.txt, line_matcher_order.txt); no --full-cache by user instruction.
- **Next step:** after PAR-227/228: `--full-cache` + `coverage_report.py`, sync coverage numbers, then decide close vs. residue.
- **Decisions:** builds on uncommitted PAR-225 (820); "has flash as long as" is modeled as the timing permission only (no keyword granted).
- **Baselines / artefacts:** v819 sizing 42 touched / 34 only; measured 32 claimed.
- **Known failures (corrected; final full-cache recheck pending):** orchestrator plain suite with PAR-225+226 in tree: 18350 passed, 489 skipped (2026-11-03). `--full-cache` deferred by the user until all PAR tickets are done.
- **Residue:** Qasali Ambusher (free cast + flash bundled, needs composite condition: singleton for hand-authoring); until-your-next-turn grants (Teferi Time Raveler, Arlinn: needs expiry state); next-spell grants with riders (Ride the Avalanche, Savage Summoning, Progenitor's Icon, Radagast, The Blue Spirit first-spell); standing with conditions/timing (Captain Mar-Vell, Final-Word Phantom, Kianne); Hungering Yeti ("green or blue permanent"), Graveyard Shift (distinct mana values), Silver Scrutiny (X), Fated Clash, Quantum Reduction, Tegwyll's Scouring; Aluren/Primal Prayers (free-cast bundles); "creature cards you own ... have flash" (Teferi x2), "familiar spells you cast have flash" (Chea), Rootwater Shaman (Aura with enchant creature), Keeper of the Secret Lair, Cherished Hatchling, Azula, Skittering Cicada/Liberator (parse now, blocked by other clauses).

## PAR-227 · Block-relation effect-body binding

- **Started / last update:** 2026-11-03 / 2026-11-03
- **Goal of this run:** extend the existing block-relation head and `trigger_related` binding to damage, characteristic and ability-change bodies referring to the other creature; distinct relations for multiple blockers and attached sources; compound bodies validated separately.
- **Done (built + tested):** PARSER_VERSION 822. New `trigger_related_referent` wrapper (`game/effects/composition.py`, isa-mapped): runs its body once per relation the firing event names, with that creature as `previous_targets`; the binder's capture (`binding/core.py`) stamps `block_related` pairs (id + zone incarnation, head `related_filter` tested at trigger time). Parser: `segmenter._block_related_body` reads the body with the group-trigger reading and re-points it at the other side of the block (damage to it and to its controller, pump, keyword gain/loss, loses all abilities, colour change, tap, doesn't untap, "the other creature" alias); fails closed for damage under an attached-host head, bare-`None` targets (would act on the source), leftover event referents, unreadable compound halves. Tests `backend/tests/test_par227_block_relation_bodies.py` (26: parse shape, refusals, real combats incl. double block, filter, attached Equipment, token trigger). Spec diff v821 -> v822: 18 newly modeled, 0 lost, 0 changed.
- **In progress:** —
- **Next step:** plain suite green after last edit (see Known failures); then orchestrator decides close (`--full-cache` deferred until all PAR tickets are done).
- **Decisions:** builds on PAR-225/226 (821, now committed); no new handler rows (existing head + body-reading path), so the pinned row-order files are unchanged. Hexproof/ward/targeting is not involved (no RULE 115 target). A related creature that left the battlefield before resolution is skipped (no LKI damage to its controller).
- **Baselines / artefacts:** calibration Ashmouth Hound, Assembled Alphas, Flailing Drake, Barrow-Blade. Newly modeled 18: Aisling Leprechaun, Ashmouth Hound, Assembled Alphas, Barrow-Blade, Cleric of Chill Depths, Flailing Drake, Inferno Elemental, Kessig Forgemaster, Labyrinth Minotaur, Mammoth Harness, Mesmerizing Benthid, Ornery Goblin, Shield of the Righteous, Skewer Slinger, Talruum Champion, Vertigo Spawn, Wall of Frost, Witherscale Wurm.
- **Known failures (corrected; final full-cache recheck pending):** —
- **Residue:** plural/"1 or more" block heads with self bodies (Amphibious Kavu, Serra Inquisitors, Dwarven Soldier, Giant Shark: head grammar, not body); Dead-Iron Sledge ("destroy both creatures"), Engulfing Slagwurm (destroy + life equal to toughness), Dream Fighter (both phase out), Corrosive Ooze / Treefolk Mystic (attachments of that creature), Shape Stealer (base P/T equal to that creature's), Godsend, Infinite Authority, Mirror Shield (quoted grant), Goblin Flotilla (compound head), Stone-Cold Basilisk (name-length filter + other clause).
