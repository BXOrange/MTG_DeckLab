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

## ENG-60 · Anthem group scopes as structured selectors

- **Started / last update:** 2026-11-16 / 2026-11-16
- **Goal:** audit every reader of the flat group params (`subtype`/`color`/`tokens`/`card_type`/`exclude_self`/`object_filter`, named `affects` strings) the static `parse_scope` family emits; move emitters + readers to structured `affects` selectors `{"zone":"battlefield","of":"you"|"any","filter":<matches_object_filter dict>}`, family by family.
- **Audit (milestone 1):** emitters = `object_scope.parse_scope_params` (creature groups), `permanent_scope_params` (bare artifact/land/enchantment/permanent), `vehicle_scope_params`; callers `rows_grants` (anthem, grant_keyword, quoted grants), `rows_attached` (group protection), `combat_restrictions`, `static_conditions._qualified_affects`, color-statement row. Sole group reader: `continuous.group_selector_objects` (via `affected_objects`, 25+ layer loops all use `affected_objects`, none reads the flat keys itself); other `params.get("subtype"/"card_type"/"color")` hits in continuous.py (cost reduction ~5647-5712, enters_tapped 7392, cast prohibition 6074, grant_evoke 7058 ...) belong to OTHER emitters (cost/tax/cast rows), not parse_scope. Other `ability.affects` readers: `==` compares only (fine for dicts) + wire summary / `_describe_ability` (dict -> `_affects_label` string, frontend `playerPanels.js` prints `e.affects`) + parser `tokens_animate_misc` emblem set-membership (dict is unhashable -> `_emblem_unsupported_affects`). `core.py:1648` / `counters_tokens._locked_group_ids` read `static.params.affects` into `previous_selector`/group (already dict-safe via `previous_group_objects`). Card counts (MODELED, by shape): creature groups ~700 (anthem other_creatures_you_control+subtype 100, grant_keyword creatures_you_control 65 / +subtype 47 / +object_filter 39, anthem creatures_you_control 42/33/27, grant_keyword all_creatures+subtype 43 ...); bare permanent/vehicle scopes ~60 (grant_keyword permanents_you_control+card_type 7, artifacts_you_control 5 ...); hand-authored `card_catalogue` entries keep string selectors / flat params: reader stays backward-compatible (smaller faithful change, no per-card rewrite).
- **Done (milestone 1, PARSER_VERSION 920):** `parse_scope_params`, `permanent_scope_params`, `vehicle_scope_params` emit structured `affects` (`{"zone":"battlefield","of":"you"|"any","filter":{...}}`); flat subtype/color/tokens/card_type/exclude_self/object_filter/*_from_source retired from these emitters (probe: 0 group-selector specs from them still carry flat keys). Engine: `_structured_selector_objects` accepts `of: any` with no controller; `_affects_label` for the wire summary/trace; emblem guard `_emblem_unsupported_affects`. Masked diff vs fresh baseline: 0 lost, 0 gained, 818 MODELED shape-only changes (all new pair keys are `affects.zone/of/filter` + `filter.*` keys read by `combat.matches_object_filter`). New tests `tests/test_eng60_structured_group_selectors.py` (39); 25 old shape assertions updated.
- **In progress:** final full-suite run (no --full-cache) after lock regen.
- **Next step (milestone 2):** remaining flat-key group emitters (outside parse_scope: `named_choice`/type_change "creatures you control are <subtype>" ~11, cost/tax `card_name_from_source`/subtype, enters_tapped_static/activation_prohibition `card_type`+`nonbasic` ~25, multi-type list scope `card_type` list on `permanents_you_control` ~15, `grant_*`/`combat_restriction` string selectors `creatures_opponents_control`/`commander_creatures_you_own`/`soulbond_pair`); then hand-authored `card_catalogue` entries (90 use `creatures_you_control`/`other_creatures_you_control`/`all_creatures` strings; reader stays backward-compatible until they are migrated); only then delete the named string branches from `group_selector_objects` and the flat-param tail (subtype/color/tokens/card_type/exclude_self) if no reader/emitter is left. `--full-cache` at ticket close.
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <where baselines, dumps and probes live>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## ENG-60 · Anthem group scopes as structured selectors

- **Started / last update:** 2026-11-16 / 2026-11-16
- **Goal:** audit every reader of the flat group params (`subtype`/`color`/`tokens`/`card_type`/`exclude_self`/`object_filter`, named `affects` strings) the static `parse_scope` family emits; move emitters + readers to structured `affects` selectors `{"zone":"battlefield","of":"you"|"any","filter":<matches_object_filter dict>}`, family by family.
- **Audit (milestone 1):** emitters = `object_scope.parse_scope_params` (creature groups), `permanent_scope_params` (bare artifact/land/enchantment/permanent), `vehicle_scope_params`; callers `rows_grants` (anthem, grant_keyword, quoted grants), `rows_attached` (group protection), `combat_restrictions`, `static_conditions._qualified_affects`, color-statement row. Sole group reader: `continuous.group_selector_objects` (via `affected_objects`, 25+ layer loops all use `affected_objects`, none reads the flat keys itself); other `params.get("subtype"/"card_type"/"color")` hits in continuous.py (cost reduction ~5647-5712, enters_tapped 7392, cast prohibition 6074, grant_evoke 7058 ...) belong to OTHER emitters (cost/tax/cast rows), not parse_scope. Other `ability.affects` readers: `==` compares only (fine for dicts) + wire summary / `_describe_ability` (dict -> `_affects_label` string, frontend `playerPanels.js` prints `e.affects`) + parser `tokens_animate_misc` emblem set-membership (dict is unhashable -> `_emblem_unsupported_affects`). `core.py:1648` / `counters_tokens._locked_group_ids` read `static.params.affects` into `previous_selector`/group (already dict-safe via `previous_group_objects`). Card counts (MODELED, by shape): creature groups ~700 (anthem other_creatures_you_control+subtype 100, grant_keyword creatures_you_control 65 / +subtype 47 / +object_filter 39, anthem creatures_you_control 42/33/27, grant_keyword all_creatures+subtype 43 ...); bare permanent/vehicle scopes ~60 (grant_keyword permanents_you_control+card_type 7, artifacts_you_control 5 ...); hand-authored `card_catalogue` entries keep string selectors / flat params: reader stays backward-compatible (smaller faithful change, no per-card rewrite).
- **Done:** family 1 = `parse_scope_params` emits structured `affects` (flat subtype/color/tokens/card_type/exclude_self/object_filter/subtype_from_source/color_from_source/card_name_from_source retired from this emitter); `_structured_selector_objects` accepts `of: any` with no controller; `_affects_label`; emblem guard.
- **In progress:** fix tests asserting old shapes; masked diff + pairkeys; PARSER_VERSION 920 + history + lock; new test file `tests/test_eng60_structured_group_selectors.py`.
- **Next step:** milestone 2: migrate the flat-key group emitters outside `parse_scope` together with their readers: multi-type list scope (`card_type` list on `permanents_you_control`), "creatures you control are <subtype>" type_change (`named_choice`), `enters_tapped_static`/`activation_prohibition` (`card_type`, `nonbasic`), cost/tax rows with `subtype`/`card_name_from_source` (readers in `continuous.py` ~5647/6074/7058/7392 read the keys directly), string selectors `creatures_opponents_control`/`commander_creatures_you_own`/`soulbond_pair` and `lands_you_control`-style type_change rows; then the ~90 hand-authored `card_catalogue` entries on named strings; only then drop the named-string branches and flat-param tail from `group_selector_objects`. Masked-diff baseline: `scratchpad/eng60/verify920.json`. Watch suite time: 248s -> 279s after milestone 1 (filter-based matching in layer recompute); profile `_structured_selector_objects` if it grows. `--full-cache` at close.
- **Decisions:** RULE 613 behaviour unchanged; reader keeps named selectors and flat params for hand-authored/other emitters; `--full-cache` only at close.
- **Baselines / artefacts:** scratchpad `eng60/base.json` (maskdump @919), `eng60/pk_base.json` (pairkeys @919), `eng60/shapes.json` (pre-change shapes), `eng60/probe.py` (post-change leftover-key probe); version lock regenerated for 920.
- **Known failures:** —
- **Residue:** —
