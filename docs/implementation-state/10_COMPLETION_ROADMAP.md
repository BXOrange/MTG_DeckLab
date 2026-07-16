# Completion Roadmap

The single, dependency-ordered plan for finishing the implementation. It
consolidates the granular backlogs and the design docs into milestones you
can execute in order.

**Live sources this reconciles**

- Granular open items: [`backend/ToDo_Backend.md`](../../backend/ToDo_Backend.md),
  [`frontend/ToDo_Frontend.md`](../../frontend/ToDo_Frontend.md)
- Shipped: [`Done_Backend.md`](Done_Backend.md),
  [`Done_Frontend.md`](Done_Frontend.md)
- User-facing coverage: in-app **Engine-Status** tab
  (`../../frontend/src/js/implementationStatusView.js`)
- Oracle parser design: [`09_ORACLE_EFFECT_PARSER.md`](../concepts/09_ORACLE_EFFECT_PARSER.md)
- Rule lookups: [`Reference/rules_wiki/`](../Reference/rules_wiki/) (`RULE <n>` → CR line)
- Archived Weeks 1–4 roadmap: [`history/IMPLEMENTATION_STATUS.md`](history/IMPLEMENTATION_STATUS.md)

---

## Where we are

The **rules-engine core is built** and green (781 backend tests): full
turn/stack/SBA loop, London mulligan, targeting, the complete mana model,
all common combat/evasion keywords (incl. landwalk), the RULE 613 layer
system essentially in full (layers 1 partial/2/4/5/6/7a–e, timestamp-ordered
within a layer, plus cost adjustment), activated/triggered/static abilities
with cost parsing (incl. loyalty `[±N]`), replacement effects, a growing set
of one-shot effects, interactive trigger ordering and per-trigger target
choice, commander damage + commander tax, planeswalker loyalty abilities,
Aura/Equipment/Fortify/Reconfigure attachment, conditional enters-tapped
lands, basic card structures (DFC transform, MDFC back-face casting, token
copies, `become_copy`, Saga lore counters), and a basic interactive priority
primitive. M3 and M4 below (layer system, permanent subsystems) are
**done** in all but two deliberately-deferred corners (layer 3 text-changing,
full 613.8 dependency ordering — see M3).

The dominant remaining gap is still that **card text does not yet fully
become behaviour**: a spell/ability only does something if its card is in
the hand-authored `game/ability_catalogue.py` **or** the oracle-text parser
(`parser/oracle/`) recognizes its clause shape as `MODELED`. The parser
already covers a good chunk of common instants/sorceries/ETB-triggers/
activated/static-anthem shapes; several effect families (regenerate, modal
"choose one"/"up to N" targets) and most parametric-keyword *behaviour*
(kicker/escape alt-costs, annihilator/afflict combat maths) are still open.
That's why the oracle parser is still Milestone 1, now joined by M5
(multiplayer/priority wiring) as the other big remaining lift — everything
else is comparatively narrow, additive work.

---

## Comprehensive-Rules coverage at a glance

| CR area | State | Notes |
| --- | --- | --- |
| 100–123 Game concepts | ✅ mostly | mana, life, damage, counters, targets, costs, timing (solo + basic interactive priority), tokens. Emblems (114), Stickers (123) not modeled. |
| 200–213 Parts of a card | ✅ mostly | Card model complete, loyalty tracked and playable. Defense (210)/Battles not. |
| 300–315 Card types | ◐ | artifact/creature/enchant/instant/land/sorcery/planeswalker done, incl. Aura/Equip/Fortify/Reconfigure attachment. Battles/dungeons/adventure/split not; Saga/DFC partial (see 700–733). |
| 400–408 Zones | ✅ | battlefield/stack/hand/library/graveyard/exile/command all present. |
| 500–514 Turn structure | ✅ | complete, walked from a sequence with skip effects. |
| 600–616 Spells/abilities/effects | ◐ | casting/activated/triggered/static/mana/replacement/loyalty (606) done; layers (613) done except layer 3 + full dependency ordering (deliberately deferred, see M3); replacement/prevention ordering (616.1e/f) is interactive, by the affected player. |
| 700–733 Additional | ◐ | SBAs (704) done; keyword abilities (702) recognized + bound (flag + landwalk); keyword *actions* (701) partial via effects. Copying (707): token copies + `become_copy` done, not a true layer-1 continuous effect. DFC transform (712.3–9) + MDFC back-face cast (712.10) done; Saga (714) lore-counter mechanics done, chapter *abilities* not; Adventure (715)/Split-Fuse (709)/Class (716)/Leveler (711)/Day-Night (731)/Monarch/Initiative not. |
| 800–811 Multiplayer | ✖ | interactive `pass_priority(player)` primitive built; `create_multiplayer` still raises, route returns 501. |
| 900–905 Casual variants | ◐ | Commander (903) damage + command zone + tax (903.8) done. Others not. |

---

## Milestones (execute in order)

Each milestone lists its goal, the concrete work, what it unblocks, and the
reference. Frontend UI work is called out per milestone; it can proceed in
parallel once the backend seam exists.

### M1 — Oracle-effect parser (keystone, in progress)
**Goal:** arbitrary `oracle_text` → `AbilitySpec` IR → `GameEffect`, so
spells/abilities resolve without a hand-authored catalogue entry.
Follows [`09_ORACLE_EFFECT_PARSER.md`](../concepts/09_ORACLE_EFFECT_PARSER.md). Phase 0
(IR + binder + one card) and the Phase 1 *keyword* catalogue are **done**.

- ✅ Normalizer + segmenter (`parser/oracle/normalize.py`, `segmenter.py`):
  split abilities on newlines, peel trigger wrapper → `EventType`, "you may"
  → optional, chain effect clauses.
- ✅ Deterministic effect-family handler table (`catalogue/handlers.py`) for
  damage/draw/discard/destroy/gain_life/counter/mill/exile/tap/±1/±1 counters/
  **pump/scry**/token creation, with shared TARGET/NUMBER/COUNT sub-grammars
  (`catalogue/subgrammars.py`). Tokens carry the full RULE 704.5d cease-to-exist
  lifecycle (`GameObject.is_token`, `RulesEngine.create_token`/
  `_remove_stranded_tokens`). *(search stays catalogue-authored — a later family.)*
- ✅ Fail-closed full-span **coverage gate** (`gate.py` `parse_oracle` →
  `MODELED`/`UNMODELED` + unclaimed-clause list). Wired into
  `ability_catalogue.specs_for` (unregistered + `MODELED` only). Tests in
  `test_oracle_pipeline.py`.
- ✅ **Activated-ability** clause parsing (`<cost>: <effect>` → `costs.py` +
  the handler table; mana abilities recognised, loyalty deferred to M4 —
  which itself is now done).
- ✅ Deduped, template-abstracted **processing list** + cache-wide coverage
  metric (`processing_list.py` `coverage_report`/`coverage_over_cards`).
- ✅ **Static/anthem clause** handler (`catalogue/static_handlers.py`): plain,
  tribal lords, token anthems, colour-scoped ("Black creatures …", Bad Moon),
  **global** (no "you control"), and compound "get +N/+N and have [kw]" — with
  subtype/token/color/exclude_self selectors in `continuous.affected_objects`.
- ✅ **Replacement clause binding** (the binder side): a hand-authored/parsed
  `replacement` spec builds a `ReplacementEffect` via `ReplacementRegistry`
  (`prevent_damage` shipped). Oracle-text *recognition* of replacement
  clauses (a target/duration grammar for the front-end) is still open.
- ✅ **Modal triggered abilities** (2026-07-16): "When ~ enters, choose
  one —" (RULE 700.2 wrapped in RULE 603) now parses and binds —
  `spec.py` allows `modes` on `ability_kind == "triggered"` (was
  `spell_effect`-only), `gate.py` recognizes the trigger-wrapped header
  (`_split_triggered_modal_block`, reusing `catalogue/modal.py`'s bullet
  collector and `segmenter.py`'s trigger event/condition grammar) and
  emits a `triggered` spec carrying `modes`, and the binder builds each
  mode's effects onto `TriggeredAbility.modes`. Resolution is a new
  `trigger_mode` interactive `pending_choice` in
  `game/rules_engine.py`'s `_place_triggers` — the mode is chosen as the
  ability is put on the stack (RULE 603.3), *before* any target/"you
  may" choice its chosen mode's own effects might still need (both
  choices compose correctly, including RULE 700.2e "or both" combining
  two modes' effects into one placement).
  **Real-cache yield correction**: the pre-implementation estimate
  ("33 cards") came from `processing_list`'s *abstracted* template
  count, which collapses a trigger-wrapped modal header and a bare
  modal-*spell* header with an unparseable bullet to the same
  `"choose <n> —"` template string — most of that 33 turned out to be
  the latter (unrelated, pre-existing gap), not this one. A direct scan
  (`_split_triggered_modal_block` over the live cache) found only **6**
  cards actually shaped this way (Aether Channeler, Ao the Dawn Sky,
  Atsushi the Blazing Sky, Charming Prince, Kura the Boundless Sky,
  Voracious Hydra) — and **all 6** remain `UNMODELED` today because each
  also needs a *different*, still-missing effect family in at least one
  of their modes (flicker/exile-then-return, fight, a filtered bounce
  target, "double this creature's counters", …). So this fix is
  necessary-but-not-sufficient infrastructure — real coverage-% movement
  needs those effect families too, not tracked as part of this item.
  **Lesson for future prioritization**: cross-check an abstracted
  processing-list count against a direct code-level scan before treating
  it as the true cards-unlocked figure for a specific fix — the
  abstraction is a great ranking signal but conflates root causes.
  Tests: `test_modal_spells.py` (parser/spec/binder/engine, incl. the
  `trigger_mode`/`trigger_target` choice composing and "or both").
- ✅ **"Enters with N counters" replacement effect** (RULE 614.1-style,
  2026-07-16): "~ enters (the battlefield) with N/X `<counter-type>`
  counters on it." now parses and resolves — new `catalogue/counters.py`
  mirrors `catalogue/lands.py`'s tapped-entry split
  (`entry_counters_condition(line)` classifies the clause,
  `entry_counters(card)` reads it off a card's text; both the coverage
  gate, claiming the line without emitting a spec — same non-effect-spec
  treatment as tapped-entry — and the engine
  (`game/ability_catalogue.entry_counters`) share this single source of
  truth). `RulesEngine._apply_entry_counters` is called at both existing
  `enters_tapped` call sites: `_resolve_permanent_spell`'s cast-resolution
  path, with `obj.x_paid` (RULE 107.3c: 0 if not cast for X) supplying the
  X amount, and the token-creation path (always X=0). Handles a fixed
  amount ("three +1/+1 counters"/"four ice counters"/"a charge counter",
  "a"/"an" folding to 1) and the variable "X" amount, for any counter kind
  (+1/+1, -1/-1, or a bare word like ice/charge/wish/study).
  **Real-cache yield correction** (same lesson as the modal-trigger batch
  above, cross-checked *before* committing to a number this time): a
  direct scan of the live cache found the clause on **23 cards**, not the
  14 the abstracted processing-list template suggested — the abstraction
  split the X-amount and fixed-amount phrasings into two separate
  templates that this one implementation covers together. Of those 23,
  only **2** (Steelbane Hydra, Stonecoil Serpent) had no other unclaimed
  line and so flip to fully `MODELED` immediately (cache-wide: 509 → 511
  modeled, 20.3% → 20.4%); the other 21 (mostly Hydras: Walking Ballista,
  Voracious Hydra, Hangarback Walker, Primordial Hydra, …) still need one
  or more *other* missing effect families (dies-triggers scaled by
  counter count, upkeep-trigger counter-doubling, fight, conditional-on-X
  effects) — necessary-but-not-sufficient infrastructure for most of them,
  same shape as the modal-trigger finding.
  Tests: `test_oracle_counters.py` (clause recognition + coverage-gate
  integration), `test_entry_counters.py` (engine: fixed/X amount, X=0,
  ordinary creature unaffected).
- ✅ **Fourth land-tapped clause variant** (2026-07-16): "~ enters tapped
  unless your opponents control N or more lands" (the "Turbulent" land
  cycle) — distinct from the three `_UNLESS_*_RE` shapes `lands.py`
  already had (all check *your own* board/opponent-*count*, none check
  *opponents'* land count). New `_UNLESS_OPPONENTS_COUNT_RE` in
  `catalogue/lands.py`, same `cmp`/`count` shape as the existing
  `unless_count`, plus a new `unless_opponents_count` branch in
  `RulesEngine.enter_land_tapped` summing lands across every player
  except the controller. Verified against the live cache *before*
  implementing (per the lesson above): exactly **5 cards** (the
  Turbulent Fen/Moor/Springs/Steppe/Wilderness cycle), each with no other
  unclaimed line — all 5 flip to fully `MODELED` (cache-wide: 511 → 516
  modeled, 20.4% → 20.6%), a clean full-yield batch unlike the two above.
  Tests: `test_oracle_lands.py` (clause recognition + gate integration),
  `test_land_tap_conditions.py` (engine: too-few/enough/summed-across-
  opponents/controller's-own-lands-ignored).
- ✅ **"Add 1 mana of any color" resolve-time colour choice** (2026-07-16):
  a spell/activated/triggered ability's own bare "Add 1 mana of any
  color." body — as opposed to a permanent's *mana ability*
  (`mana_abilities.py`), which already supported "any color" via its
  pre-declared tap-for-mana options and needed nothing here. New
  `_ADD_MANA_ANY_COLOR_RE`/`_add_mana_any_color` in `catalogue/
  handlers.py` emits `EffectSpec("add_mana", {"colors": ["any"]})`
  (deliberately narrow to the singular "1 mana" phrasing — real cards
  templating a multi-mana choice always say "any *one* color" instead, a
  different, still-unclaimed shape). `AddManaEffect` (`game/effects.py`)
  treats an `"ANY"` entry as a genuine resolve-time player decision
  instead of guessing: `GameContext.add_mana_any_color` →
  `RulesEngine.add_mana_any_color` opens an `add_mana_any_color`
  `pending_choice` (mirroring `counter_unless_pays`'s established
  "open a choice mid-effect-apply, the resolve loop pauses on it"
  pattern), and `resolve_add_mana_any_color_choice` finishes it — a
  missing/invalid answer defaults to White rather than dropping the
  mana, the same "defaults instead of dropping" treatment
  `resolve_trigger_mode_choice` gives a missing mode answer.
  **Real-cache yield: 0 cards**, exactly as predicted before starting
  (this was never a coverage-% play) — every real card printing this
  clause (Deathrite Shaman, Crystalline Crawler, Mana Bloom, Fertile
  Ground) is still blocked by a *different*, unrelated gap on the same
  card: a "remove a counter" activation-cost shape `costs.py` doesn't
  parse yet (Crystalline Crawler, Mana Bloom), generic "card in any
  graveyard" targeting not yet existing (Deathrite Shaman — Batch 5,
  next), or an entirely different triggered-ability event ("whenever
  enchanted land is tapped for mana", Fertile Ground). This batch is
  purely the shared primitive the plan called for — real payoff is
  Deathrite Shaman once Batch 5 also lands. Tests:
  `test_effect_families_wave3.py` (parser recognition + negative cases,
  gate-level `MODELED` integration, engine: opens the choice/resolves to
  the chosen colour/defaults to White on a missing answer).
- ✅ **Generalized graveyard-card targeting + Deathrite Shaman**
  (2026-07-16): the Regrowth/Reanimate-shaped recursion family
  (`graveyard_creature`) generalized in `game/targeting.py` from
  "creature, your own graveyard, to battlefield/hand only" to card type
  (any/creature/land/artifact/enchantment/instant-or-sorcery/permanent/
  nonland permanent) × graveyard scope (own/any single graveyard/an
  opponent's) — `_GRAVEYARD_TARGET_KINDS`, their cross product. Three
  parser handlers in `catalogue/handlers.py`: the generalized
  `return_from_graveyard` (+ "put … under its owner's control", same
  effect); a new `reanimate_under_your_control` ("put … under **your**
  control" — Reanimate/Virtue of Persistence, a genuinely different
  effect: `ReturnFromGraveyardEffect` gained `under_your_control`,
  threading a `controller_id` override through
  `RulesEngine.return_from_graveyard` so the stolen card's owner and
  controller correctly diverge); and a new `exile_from_graveyard`
  (Deathrite Shaman/Scavenging Ooze-shaped — `ExileEffect` already
  worked "from anywhere," no engine change needed).
  **Surfaced two real, previously-invisible gaps while chasing Deathrite
  Shaman's third ability to an actual runtime test**, not just the
  parser's `MODELED` verdict: (1) "X loses N life" had *no* parser
  handler or `EffectRegistry` entry at all — added `lose_life`/
  `lose_life_selector` (mirroring `gain_life`/`_damage_selector`); (2) a
  real pre-existing bug in `GainLifeEffect`/`LoseLifeEffect`, which
  silently read `targets[0]` off a *shared* ability/spell target list as
  a fallback player — correct only because no previously-modeled card
  combined either with an unrelated targeted effect in the same chain.
  Deathrite's "Exile target creature card from a graveyard. You gain 2
  life." does exactly that (`targets[0]` was the exiled card, not a
  player) and crashed with an `AttributeError` the first time it
  actually resolved. Fixed by switching both to `_controller_of(source,
  context)`, the same correct pattern `AddManaEffect` already used (why
  it never hit this). **Real-cache yield, verified via a true before/
  after diff** (a temporary handler-table monkeypatch, since this session
  never committed between batches): **19 cards** newly fully `MODELED`
  (516 → 535, 20.6% → 21.3%) — Deathrite Shaman itself, Eternal Witness,
  Regrowth, Sanctum Gargoyle, Trading Post, Trash for Treasure,
  Restoration Seminar, Revolutionist, Pinnacle Monk, Bala Ged Recovery,
  Buried Ruin, Colossal Skyturtle, Siege Zombie, Cryptbreaker, plus — a
  side benefit of the `lose_life` fix alone — Anguished Unmaking,
  Infernal Grasp, Night's Whisper, Read the Bones, Grim Tutor (well-known
  staples). Many more graveyard-shaped cards (Reanimate, Karmic Guide,
  Zombify, Puppeteer Clique, …) still have their graveyard-targeting line
  claimed but remain `UNMODELED` on a *different* line (a life-total-
  scaled amount, a `-1/-1`-counter qualifier, "up to one target", …) —
  necessary-but-not-sufficient infrastructure, same shape as the modal-
  trigger/enters-with-counters findings above. Tests:
  `test_effect_families_wave3.py` (parser recognition for every type ×
  scope combination + fail-closed negatives, gate integration, engine:
  control-steal from an opponent's graveyard, life-loss selectors, and a
  full Deathrite Shaman oracle-text-to-engine test over all 3 abilities).
- ✅ **Mana spend restrictions, RULE 605.3a** (2026-07-16): the largest
  architectural item in the plan — `models/mana_pool.py`'s flat
  `dict[str, int]` had no way to tag mana as spendable only on a subset
  of costs, so "Spend this mana only to cast a creature spell." was
  silently unenforced once produced. `ManaPool` gained a parallel
  `restricted` lot structure (a caller-supplied `allows_restriction`
  predicate opts specific lots in per payment; `None`, the default,
  keeps every pre-existing call site unaffected), and every payment call
  site that pays from a pool (`GameEngine.can_cast`/`tap_for_mana`/
  `_can_pay_activation_cost`/`_pay_activation_cost`/`_max_x_for_mana`,
  `RulesEngine.cast_spell`) now builds the right predicate from the
  spell/ability-source's printed characteristics via two new
  `game/mana_abilities.py` builders. Parser side: a new
  `_parse_restriction` recognizes the real-card vocabulary (creature/
  legendary/instant-or-sorcery/named-type spell, your commander, a cost
  containing `{X}`, several paired with "... or activate an ability of a
  \<same type\>") — a land's own "of the *chosen* type/color" and a
  mana-value-threshold clause stay unrestricted (fail-soft, not a
  regression). **Real-cache yield**: 13 of the 18 cards that already
  produce a real `ManaAbility` (of 27 total printing the clause; 9 are
  granted-ability templates excluded by a separate, pre-existing gate,
  5 more don't produce mana at all yet — Batch 7 territory) now get a
  correctly modeled restriction. Full writeup + card list:
  Done_Backend.md "Rules Engine (Phase 2)". Tests:
  `test_mana_spend_restrictions.py` (35 tests: pool mechanics, clause
  parsing, predicate builders, full engine end-to-end).
- ✅ **"Any combination of colors" mana, RULE 605.1a** (2026-07-16): "Add N
  mana in any combination of colors" (Flamebraider/Gwenna/Smokebraider's
  fixed "two", Selvala's variable "X" = greatest power among creatures you
  control) — a *split* across colours, not a single-colour choice like
  "any one colour". New `ManaAbility.any_combination` +
  `_parse_combination_selector` (literal-number and
  `greatest_power_control` amount kinds) in `game/mana_abilities.py`;
  `GameEngine.tap_for_mana` gained a `color_split` parameter
  (`validate_color_split`), consulted only for a combination ability and
  falling back to the pre-existing `option_index` single-colour default
  otherwise — additive, no existing caller changed behaviour. No split-
  choice UI yet (`frontend/ToDo_Frontend.md`). **Real-cache yield**: all 4
  cards that actually produce a combination mana ability now parse
  correctly (a 5th cache hit, Realm-Scorcher Hellkite, is a triggered ETB
  effect, not a mana ability, correctly out of scope). Full writeup:
  Done_Backend.md "Rules Engine (Phase 2)". Tests:
  `test_mana_combination.py` (17 tests).
- ✅ **Hand-zone mana abilities, RULE 605.1a** (2026-07-16): "Exile this
  card from your hand: Add …" (Elvish/Simian Spirit Guide) — a mana
  ability with no battlefield permanent and no {T} at all, activated
  straight from hand; previously had no activation path whatsoever
  (`parse_mana_abilities` deliberately excluded it, and nothing else
  picked it up). New `hand_mana_abilities`/`hand_mana_abilities_for`
  (`game/mana_abilities.py`, sharing `parse_mana_abilities`'s line
  grammar via a new `want_hand_exile` filter) + `GameEngine.
  activate_hand_mana_ability` (pays via the existing `RulesEngine.exile`
  zone-move primitive rather than the battlefield-oriented
  `_pay_activation_cost`), wired through a new `activate_hand_mana`
  legal-action kind and `game_session.py`. No frontend UI yet
  (`frontend/ToDo_Frontend.md`). **Real-cache yield**: 1 of 6 substring
  hits is a genuine hand-zone mana ability (Simian Spirit Guide); the
  other 5 are Foretell/Plot reminder text using the same phrase for an
  unrelated cost, correctly unmatched. Full writeup: Done_Backend.md
  "Rules Engine (Phase 2)". Tests: `test_hand_mana_abilities.py`
  (11 tests).
- ✅ **Regenerate, RULE 701.16 (2026-07-16):** a new `EventType.DESTROY`
  `RulesEngine.destroy` fires pre-emptively (through the existing
  `apply_replacements` machinery, additive/back-compat for every existing
  caller) so `RulesEngine.regenerate` can attach a self-consuming
  regeneration-shield `ReplacementEffect`; RULE 704.5g's lethal-damage SBA
  now routes through `destroy` so a shield can intercept it. Also fixed a
  RULE 701.16c gap this surfaced: sacrifice (`RulesEngine.sacrifice` +
  `GameEngine`'s two cost-payment sacrifice sites) previously called
  `destroy` directly, which would have let a shield illegally save a
  sacrificed permanent — all three now use the new non-destructive
  `RulesEngine.put_into_graveyard`. `RegenerateEffect` (`game/effects.py`)
  plus two parser handlers (`"regenerate target creature"` / self-form
  `"regenerate ~"`) mirror the existing `destroy`/`tap`/`tap_self` shapes.
  **Real-cache yield: zero net coverage movement (535/2507, 21.3%,
  unchanged)** — of 10 cache hits for "regenerate", 9 are "can't be
  regenerated" Destroy-tags (out of scope) and the 1 genuine ability
  (Ezuri, Renegade Leader, "Regenerate another target Elf") needs a
  subtype-filtered target shape no handler has yet, so it fails closed.
  Shipped anyway as a self-contained RULE 701.16 engine capability for
  future cache growth/hand-authoring. Full writeup: Done_Backend.md
  "Rules Engine (Phase 2)". Tests: `test_regenerate.py` (17 tests).
- ✅ **Batch 11 (2026-07-16): "up to one" targets (N=1), "if kicked"
  additional effects, replacement-clause recognition (3 of 5 families).**
  The shared `TARGET` grammar (`subgrammars.py`) now recognizes an "up to
  one "/"up to 1 " prefix for free on every `{TARGET}`-based handler
  (`optional` threaded through to each consuming effect's `TargetSpec` —
  `TargetSpec.optional`/`has_legal_targets` already understood it
  correctly, just nothing had ever set it); a real N>=2 multi-target choice
  is explicitly **not** attempted (needs an interactive multi-select + per-
  effect application over a list, a materially larger feature). A new
  `EffectSpec.condition` field (parallel to `AbilitySpec.modes`, whitelisted
  to `{"kicked": bool}`) + `game/effects.py`'s `ConditionalEffect` wrapper
  cover RULE 702.33b's "if this spell was kicked, \<effect\>." — only the
  *additional-effect* shape (Vastwood Surge), not "if kicked, ... instead"
  (overriding an existing effect's amount — Burst Lightning/Rite of
  Replication-shaped, a different unmodeled grammar). New
  `parser/oracle/catalogue/replacements.py` recognizes 3 of the 5 already-
  bound `ReplacementRegistry` families as standing permanent clauses
  (`double_tokens`/`double_counters`/`additional_damage`, Doubling
  Season/Anointed Procession/Torbran-shaped) — found and fixed a real bug
  this exposed: `gate.py`'s `ParseResult.effect_specs` excluded
  `ability_kind == "replacement"` entirely, so nothing a `replacement`
  spec claimed would ever have reached `obj.replacement_effects` despite
  parsing `MODELED`. `prevent_damage`'s two real cards (Riot Control/
  Thought Lash) are a different, unmodeled *one-shot spell effect* shape
  (Regenerate-shaped, not a standing clause) and stay open. Also: an
  `AddCountersEffect` mass `selector="each_creature_you_control"` (RULE
  601.2c) and the basic-land search handler recognizing "up to N" (both
  needed to make Vastwood Surge's own kicked clause reach `MODELED`).
  **Real-cache yield: 583 → 594 fully `MODELED` (+11, 20.3% → 20.7% of
  2,869 cards — cache grew since the last measurement), zero regressions.**
  The "up to one target" grammar itself is real and independently verified
  (9 clause instances now parse correctly) but contributed 0 whole-card
  flips this round — every one of those 9 cards has a *different* separate
  unmodeled clause on the same card; reported transparently rather than
  claimed. Full writeup: Done_Backend.md "M1 — Oracle-effect parser".
  Tests: `test_optional_targets.py` (10), `test_kicked_conditional.py`
  (15), `test_replacement_clause_recognition.py` (11), +1 in
  `test_effect_families_wave3.py` — 37 new tests.
- ⏳ **Remaining, priority-ordered by real cards-unlocked** (verified
  2026-07-16 by running `processing_list.coverage_over_cards()` over the
  live cache — 20.7% of 2,869 cards fully `MODELED`; **re-run this before
  trusting the counts below**, the cache keeps growing and the ranking
  shifts):
  1. A real "up to two/three/N"/"up to X" **multi**-target choice (N>=2,
     see Batch 11 above for why it's a separate, larger feature from the
     N=1 case just shipped), a "remove a counter from ~" activation-cost
     shape (`costs.py` — newly surfaced by an earlier batch's real-card
     debugging, blocks Crystalline Crawler/Mana Bloom/Walking Ballista/
     Triskelion/Wishclaw Talisman/Transmogrifying Wand — plausibly the
     next highest-leverage single fix, not yet template-ranked), a
     life-total-scaled amount ("lose life equal to that card's mana
     value" — Reanimate/Rise from the Grave/Kenrith, newly surfaced by
     an earlier batch, blocks otherwise-complete graveyard-recursion
     cards), the remaining RULE 616.1 replacement-clause formulations
     (`prevent_damage`'s one-shot-spell shape, differently-scoped/
     compound-filter variants — see Batch 11), a kicked spell's "if
     kicked, ... instead" *override* shape (as opposed to the additional-
     effect shape Batch 11 covers), parse-on-load memoization in
     `LazyCardLoader`, and the processing-list tail — current top
     blockers per the live ranking: "choose \<n\> —"/"choose \<n\> or
     more —" (31+6 cards, a genuinely larger grammar than RULE 700.2's
     "choose one"/"choose one or both", still unclaimed), "you may look
     at the top card of your library any time" (13), "when this land
     enters, surveil \<n\>." (10), "\<cost\>: level \<n\>" (9),
     monarch/initiative (7-9 each, deferred per M6), cost-modification
     statics, and emblems.
  - **Related, same pipeline, separately tracked in `ToDo_Backend.md`**:
    the mana-ability follow-up list from the 2026-07-15 Elf-mana-dork pass
    is now fully done (spend restrictions, Leveler-gating, Deathrite
    Shaman, "any combination of colors", and hand-zone activation) — not
    cache-coverage-ranked since mana abilities are recognized without
    needing a `MODELED` spec.
- **Unblocks:** plain instants/sorceries/ETB-triggers/activated/static
  abilities from the handled families already resolve with no catalogue
  entry; is the seam M2 plugs into. *(docs/09 Phases 1–2.)*

### M2 — Parametric keyword binding — done
**Goal:** give behaviour to keywords already parsed-but-inert.

- Landwalk is **done** (fully bound into combat, RULE 702.14) — the first
  parametric keyword to go all the way from parse → parameter → behaviour.
- **Annihilator/afflict/bushido and hexproof are done** (2026-07-15):
  `effect_binder._keyword_triggered_abilities` synthesizes real
  `TriggeredAbility`s for the three combat-math triggers (routed through the
  ordinary stack, not special-cased in `combat.py`), backed by a new
  `EventType.BECOMES_BLOCKED` (fires once per attacker transitioning from
  unblocked to blocked) plus new `SacrificeEffect`/`LoseLifeEffect`
  one-shots; hexproof gates `targeting.legal_targets` via
  `combat.has_hexproof`.
- **Ward is done** (2026-07-15, rules-accurate as of the same day):
  `RulesEngine.check_ward`, called wherever a spell/activated/triggered
  ability's targets are finalized (`cast_spell`/`cast_without_paying`/
  `_place_trigger`/`GameEngine.activate_ability`), pushes a genuine
  `StackItem` (a `WardEffect`) on top of the triggering item for every
  warded target — a real triggered ability per RULE 603.3, not an inline
  choice, so normal priority-passing gives both players a response window
  before it resolves; RULE 702.21c's multiple-simultaneous-ward case needs
  no special sequencing since each ward is its own stack object and the
  stack naturally resolves them one at a time. The pay-or-counter decision
  (belonging to the *caster*, unlike `counter_unless_pays`'s target-
  controller) reuses `ActivationCost`/`costs.parse_activation_cost` — the
  same mana/pay-life/discard/sacrifice vocabulary an activated ability's
  cost already uses — via a small parser fix (`keywords.py`'s
  `_WARD_TEXT_COST_RE` fallback, since the shared COST-shape regex is
  mana-only and previously dropped a non-mana ward clause entirely).
- **Alternative/additional-cost keywords are done** (2026-07-15): Kicker/
  Multikicker (an optional, cast-time-parameterized additional cost — the
  same `x`/`mode` shape `GameEngine.cast_spell` already uses for `{X}`/modal
  spells, plus a new `ManaCost.add` to compose it with the printed cost),
  Buyback (same shape, plus a `RulesEngine.resolve_top_of_stack` branch
  returning the spell to hand instead of the graveyard), and Flashback/
  Escape (a shared graveyard-cast zone gate in `GameEngine.can_cast`/
  `legal_actions`, each substituting its own alternative cost for the
  printed one; Flashback exiles the spell after resolving, Escape resolves
  normally). Escape's own new cost-grammar work: "exile N other cards from
  your graveyard" — previously silently dropped by the mana-only COST-shape
  extractor — now parses via a new `_ESCAPE_TEXT_COST_RE` free-text fallback
  plus `ActivationCost.exile_from_graveyard`/`_EXILE_GRAVEYARD_RE`
  (`game/costs.py`). See `Done_Backend.md` "Rules Engine (Phase 2)" for the
  full writeup. Not part of this slice (a deliberate follow-up, tracked in
  `ToDo_Backend.md`'s M1 section): a spell's "if this spell was kicked, …"
  resolve-time conditional effect doesn't yet consume
  `GameObject.kicker_count` — that needs new oracle-parser
  conditional-clause grammar, not cost-mechanic wiring.
- **Rampage is done** (RULE 702.23, 2026-07-15) — the same "per-firing
  dynamic effect amount" problem Ward solved, solved the same way: new
  `RulesEngine.check_rampage`, called from `GameEngine.declare_blockers`
  right where `BECOMES_BLOCKED` fires, builds a fresh `TriggeredAbility`
  with a `PumpEffect` sized to that specific block's blocker count and
  pushes it via the existing `_place_trigger` — a real stack object, not an
  inline effect. See `Done_Backend.md` "M2 Rampage" for the full writeup.
- Remaining narrow rough edges, not new features: a ward cost with `{X}` in
  it (RULE 702.21b) isn't specially resolved (no known real card needs it);
  protection *quality* (already fully working via a separate, older path —
  `combat.is_protected_from` — not `parametric_keywords` at all); and
  hexproof-*from*'s quality (currently aliased onto plain hexproof, losing
  the "from X" scope) — see `ToDo_EdgeCases.md`. Every parametric keyword
  this engine models now binds onto `GameObject.parametric_keywords` *and*
  consumes it: landwalk/annihilator/afflict/bushido/ward/rampage/kicker/
  buyback/escape/flashback.
- **Depends on:** M1 keyword catalogue (done) + cost/targeting systems (done).

### M3 — Layer system completion (RULE 613) — done, narrowly scoped in two corners
**Goal:** finish `game/continuous.py` to the full layer set.

- ✅ Layers 2 (control), 4 (type), 5 (colour), 6 (ability-adding — incl.
  granting a non-keyword mana/triggered ability, not just a keyword slug),
  7a (CDA), 7b–d (set/counters/pump), 7e (P/T switch) — all bridged by the
  `StaticAbility`/`EffectRegistry`, timestamp-ordered within a layer.
- ◐ Layer 1 (copy effects, RULE 707): `become_copy` mutates the object in
  place rather than running as a per-recompute layer-1 pass; see M6.
- ✅ **Layer 3 and RULE 613.8 dependency ordering are built** (2026-07-14,
  reopening a 2026-07-09 "deliberately not built" decision), each narrowly
  scoped rather than fully general — see
  [ToDo_EdgeCases.md](ToDo_EdgeCases.md) "Layers / static abilities" for the
  exact scope of each and `backend/ToDo_Backend.md`'s "Static abilities /
  continuous-effects layer system" entry for the full writeup.
- **Depends on:** layer 1 overlaps with M6 copying.

### M4 — Permanent subsystems — done
**Goal:** the four independent, medium-sized permanent mechanics below.
All four are **done**:

- ✅ **Loyalty / planeswalker abilities (606):** loyalty-cost kind in
  `costs.py`, sorcery-speed + once-per-turn gate, `[+N]/[-N]/[0]`
  activation, 0-loyalty SBA (704.5i), planeswalker damage marking. *UI:*
  still open — clickable loyalty controls (`ToDo_Frontend.md`).
- ✅ **Aura / Equipment attachment (303 / 301.5 / 702.6/67/151):** Aura ETB
  attaches to target (303.4f); equip/fortify/reconfigure as sorcery-speed
  activated abilities; `continuous.recompute` reads `attached_to` into
  layers 6/7 (`affects="attached_permanent"`). Remaining sliver:
  re-validating an *existing* attachment's legality every SBA pass (today
  only "host left the battlefield" is checked). *UI:* still open — cast
  target for Auras, "Ausrüsten" control (`ToDo_Frontend.md`).
- ✅ **Commander tax (903.8):** per-commander from-command-zone cast counter
  on the player, read by the cost calc, carried by rewind snapshots.
- ✅ **Conditional enters-tapped (614.1):** shock/check/fast/slow lands — a
  replacement-effect + player choice (pay life) or deterministic board
  evaluation instead of a plain boolean. *UI:* still open — pay-2-life
  prompt (`ToDo_Frontend.md`).

### M5 — Interactive priority, multiplayer & ordering choices (in progress)
**Goal:** two humans can hold priority and respond.

- ✅ Interactive priority **primitive**: `GameEngine.pass_priority(player)`
  (RULE 117.3-4) resolves the stack only once every living player has
  passed in succession, otherwise advances APNAP; any real action reclaims
  priority. Solo/goldfish auto-resolve is unchanged when called with no
  player.
- ✅ Player-made **ordering choices**: triggers within a controller (603.3b,
  opt-in `interactive_ordering`) and a triggered ability's own target/"you
  may" choice (115/603.3c/603.5) are both interactive. Known narrow gap:
  the two together (a targeted trigger placed via the manual-ordering path)
  isn't handled.
- ✅ Replacement/prevention ordering by the affected player (616.1e/f) is
  interactive: `RulesEngine.apply_replacements` opens a `replacement_order`
  `pending_choice` whenever 2+ apply simultaneously (`Done_Backend.md`
  "Replacement ordering").
- ⏳ Still open: wire `WebSocket /ws/game/{id}` into a server-held session
  (run the action through the engine, broadcast `GameState.to_dict()`);
  remove the `create_multiplayer` stub; interactive **blocker declaration**
  UI (engine-ready via `declare_blockers`, no opponent-side UI yet).
- **UI:** opponent zones, hidden opponent hand, turn/priority indicator,
  per-creature attacker subset selection, slow-opponent timeout — all still
  open (`ToDo_Frontend.md` "Multiplayer").

### M6 — Card-type structures (partial)
Each is a `type_line`/layout the parser or a dedicated handler must own; most
depend on M1, and copies feed M3's layer 1.

- ✅ Double-faced transform on the battlefield (712.3–9, `GameObject.transform`)
  and **MDFC back-face casting/playing from hand (712.10)** — both faces
  offered as independent actions, rejected back-face cast rolls back.
  Remaining: a transform *trigger/effect* to call `transform()`, Day/Night
  (731), MDFC commanders cast from the command zone (known deliberate gap).
- ✅ Saga (714) lore-counter mechanics (enter with one, +1 after draw step,
  sacrifice at final chapter). Remaining: the chapter *abilities* firing per
  counter. Class (716)/Leveler (711) not started.
- ✅ Copying objects (707): token copies (`copy_permanent`) and "becomes a
  copy of" (`become_copy`, modeled as an ordinary ETB trigger rather than
  true 614.1c/614.12 replacement timing) are both done and interactively
  playable. Remaining: the true layer-1 continuous-effect version (M3).
- Adventure (715) & Split/Fuse (709): recognised structurally
  (`Card.is_adventure`/`is_split`) but still resolve as the single
  front-face spell — not started.
- Battles (310), Dungeons (309) — not started.
- Deprioritized until a deck needs one: Emblems (114), Stickers (123), Monarch
  (725) / Initiative (726), Rad counters (728), remaining multiplayer/casual
  variants.

### M7 — Product features (parallel track, not rules-engine)

- **Deck analysis (UC2):** the **static/heuristic half is done** —
  mana curve, type distribution, land archetypes, Command Zone categories,
  and a WotC-Commander-Brackets-style heuristic all ship client-side, no
  backend call (`Done_Frontend.md` "Deck analysis (UC2)"). Still
  open: the **LLM-backed** narrative half — `POST /api/decks/{id}/analyze`
  (Claude API, prompt templates, structured output, caching; design the
  `Analysis` model alongside — the reserved `Deck.analysis_id` shape isn't
  final). *UI:* analyze button + narrative results view + cache indicator,
  additive to the existing static/Bracket sub-tabs. Use the latest Claude
  models.
- **Auth & persistence:** accounts/login, scope saved decks to an owner, game
  history/session persistence. *UI:* login/signup, token storage, reconnect.
- **Bot AI (UC5):** upgrade the greedy `run_goldfish_turn` to weigh lines.
  *UI:* bot-vs-manual selector, action visualization + speed control.
- ✅ **External deck-builder import:** Moxfield tried twice (client-side,
  then a server-side proxy) and reverted both times — confirmed via a
  live test against a real deck id that Cloudflare genuinely blocks it
  (not just a CORS/header issue), so it'd need a headless-browser
  fallback or residential-IP proxy to actually work (backend ToDo
  "Import — follow-up from the frontend"). Archidekt's API has no such
  block (plain unauthenticated request → real deck JSON) — shipped as
  its own "Import Deck" sidebar tab (`Done_Backend.md`/`Done_Frontend.md`
  "Import").

---

## Suggested sequencing

```
M1 (oracle parser) ──┬─▶ M2 (parametric keyword behaviour) ── done
                     └─▶ M6 remainder (Adventure/Split, Battles/Dungeons)
M3 (layers)          ── done except two deliberately-deferred corners
M4 (permanent subsystems) ── done (engine-side); UI hookups remain in ToDo_Frontend.md
M5 (priority/multiplayer) ── primitive + ordering choices done; session/WS wiring + blocker UI remain
M7 (product: LLM analysis / auth / bot) ── parallel track, no rules-engine dependency;
                                             static deck analysis already shipped
```

**Critical path to "most decks are playable solo":** M1 → M2. Full
two-player play additionally needs the rest of M5. Everything in the
remainder of M6/M7 is additive.
