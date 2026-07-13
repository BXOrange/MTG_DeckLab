# Backend TODO

Open backend items. Completed work has moved to
[Done_Backend.md](../docs/implementation-state/Done_Backend.md) (section
headers there mirror these).
See [../docs/implementation-state/10_COMPLETION_ROADMAP.md](../docs/implementation-state/10_COMPLETION_ROADMAP.md)
for the dependency-ordered plan to finish the implementation. The original
Weeks 1–4 roadmap is archived at
[../docs/implementation-state/history/IMPLEMENTATION_STATUS.md](../docs/implementation-state/history/IMPLEMENTATION_STATUS.md).

## Configuration (Backlog)

- [ ] On-disk paths (`CACHE_ROOT`/`DEFAULT_DB_PATH` in
      `card_database.py`, `DATA_ROOT`/`DEFAULT_DECKS_DB_PATH` in
      `deck_database.py`) are hard-coded module constants with no
      override hook. Came up concretely: verifying a change against a
      real running server means pointing it at these same fixed,
      repo-relative paths as any dev instance you might have running —
      there's no way to redirect a one-off/test server elsewhere, so
      the two can collide (a cleanup between test runs can wipe a dev
      server's actual cache/saved decks out from under it). With schema
      versioning now in place a stray script pointed at `DEFAULT_DB_PATH`
      *clears* rather than just reads it — extra reason to make paths
      overridable. Pull these — and other scattered constants, e.g.
      `scryfall_client.py`'s `_USER_AGENT`/`_MIN_REQUEST_INTERVAL_SECONDS`,
      `image_cache.py`'s `_USER_AGENT` — into one config module (e.g.
      `mtg_analyzer/config.py`), reading overrides from environment
      variables (e.g. `MTG_CACHE_DIR`, `MTG_DATA_DIR`) with the current
      hard-coded values as defaults. `api/dependencies.py`'s singletons
      would read from there instead of importing the path constants.

## Rules Engine (Phase 2) — remaining

- [ ] Oracle-text → effect *parser* (docs/07 PART 5): spells still carry
      no auto-derived effects, so an instant/sorcery resolves as a no-op
      unless a fixture attaches effects via the `spell_effects`/ability
      hooks. A growing set of one-shot effects + the registry exist —
      damage/draw/discard/destroy/gain_life/counter/search (see Done
      "Rules Engine") — but nothing turns a card's `oracle_text` into
      them yet; that parser is the gap. Search is basic type/subtype
      matching only; richer criteria (mana value, colour, "you may")
      belong here too. **Design agreed** in
      [../docs/concepts/09_ORACLE_EFFECT_PARSER.md](../docs/concepts/09_ORACLE_EFFECT_PARSER.md):
      two-stage compiler (front-end parses `oracle_text` → `AbilitySpec`
      IR; binder maps IR → `GameEffect` via the registry), a
      repo-committed handler catalogue (regex + builder) vs. the volatile
      card cache, parse-on-load / bind-per-game linking, and a fail-closed
      full-span coverage gate (`MODELED`/`UNMODELED`, unclaimed clauses →
      processing list → analyzer). Start at Phase 0 (IR + binder + one
      hand-wired card, no NLP).
      **Progress:** the Phase 1 *keyword catalogue* is in —
      `parser/oracle/catalogue/keywords.py` maps the full RULE 702 vocabulary
      (194 keywords) to its `AbilitySpec` shape (flag / number / cost /
      number+cost / quality) with a regex that extracts each parametric
      keyword's one parameter; `parse_keywords(card)` anchors on Scryfall's
      `keywords` array and pulls the parameter out of oracle text, emitting
      validated `keyword` specs (`AbilitySpec.keyword = {name, n?/cost?/
      quality?}`). **Flag keywords now bind**: `specs_for` folds the parsed
      keyword specs in, and the binder docks parameterless ones onto
      `GameObject.intrinsic_keywords`, which `game/combat.py` unions into its
      recognition.
      **Phase 1 shipped (the effect-clause front-end):** `parser/oracle/`
      now has `normalize.py` (reminder-strip, self-name → `~`, digit-word fold,
      newline-preserving), `catalogue/subgrammars.py` (shared TARGET/NUMBER/
      COUNT matchers — one damage handler covers "any target"/"target creature"/
      …), `catalogue/handlers.py` (the effect-family table: damage/draw/discard/
      gain_life/destroy/counter, each full-matching a clause), `segmenter.py`
      (peels trigger wrappers → `EventType`, "you may" → optional, splits chained
      clauses), and `gate.py` (`parse_oracle(card)` → `AbilitySpec`s + a
      fail-closed `MODELED`/`UNMODELED` coverage verdict + unclaimed-clause list).
      `ability_catalogue.specs_for` falls back to it for **unregistered** cards,
      adding effect/triggered/activated specs **only when the card is `MODELED`**
      (never half-resolves). So a plain instant/sorcery/ETB-trigger/activated
      ability built from the handled families now resolves with no catalogue
      entry. Handled effect families: damage, draw, discard, destroy, gain_life,
      counter, **mill, exile, tap/untap, +1/+1 counters, and token creation**
      (backed by new one-shot effects `MillEffect`/`ExileEffect`/`TapEffect`/
      `AddCountersEffect`/`CreateTokenEffect` + engine primitives
      `RulesEngine.exile`/`set_tapped`/`add_counters`/`create_token` and the
      pre-existing `mill`). **Tokens** carry the rules-critical lifecycle:
      `GameObject.is_token` (stored, so a token *copy* of a real card is still a
      token), creation binds the token's abilities like any card's, and a new
      SBA `RulesEngine._remove_stranded_tokens` implements RULE 704.5d — a token
      that leaves the battlefield reaches its zone long enough to fire its
      dies/leaves triggers, then ceases to exist and can't return (RULE 111.7-8);
      exile and destroy both funnel through it. +1/+1 counters may target any
      permanent, not only creatures (RULE 122.1a). **Activated abilities** are
      parsed too: the segmenter peels a
      `<cost>: <effect>` wrapper, feeds the cost to `costs.parse_activation_cost`
      and the effect body to the same handler table (mana abilities — "add …" —
      are recognised as covered-without-a-spec, since the engine models them
      separately; loyalty "[+N]:" costs stay `UNMODELED`, deferred to M4).
      `parser/oracle/processing_list.py` adds the **coverage metric + ranked,
      template-abstracted processing list** (docs/09 "coverage is the roadmap"):
      `coverage_report(...)`/`coverage_over_cards(cards)` → `% MODELED` + the
      unclaimed-clause templates ranked by cards-unlocked. Tests:
      `test_oracle_pipeline.py`.
      **Static/anthem clauses parse too** (`parser/oracle/catalogue/
      static_handlers.py`): "creatures you control get +N/+N", tribal lords
      ("Other Goblins you control …" — singularised), token anthems (Intangible
      Virtue), and compound "get +N/+N and have [flag keywords]" become `static`
      `AbilitySpec`s (`anthem`/`grant_keyword`). `continuous.affected_objects`
      gained **subtype**, **tokens**, **color**, and **exclude_self** selectors
      (Changeling matches any subtype; colour vs `card.color_identity`); scope
      also covers **global** anthems (no "you control" → all creatures, both
      players — Bad Moon/Crusade), "all"/"each" markers, and multicolour scopes.
      **Landwalk now binds**: `game/combat.py` has landwalk evasion
      (`landwalk_subtypes`/`unblockable_by_landwalk`, RULE 702.14, consulted by
      the engine's `can_block`), the binder docks a landwalk keyword spec onto
      the `<type>walk` slug (`attach_keyword`), and a layer-6 grant of it flows
      through. **`replacement` binding is in**: `bind_ability` builds
      `ReplacementEffect`s from a `replacement` spec via a new
      `ReplacementRegistry` whitelist (`prevent_damage` shipped), attached to
      `obj.replacement_effects`. **Parametric keywords bind** their parameter
      onto `GameObject.parametric_keywords` (annihilator N, kicker cost, ward,
      protection quality — carried for the consumers; landwalk is fully wired).
      **More effect families shipped**: `pump` ("+N/+N until end of turn",
      also −N/−N and a "gains \<keyword\> until end of turn" grant — a temporary
      `GameObject.temp_power/temp_toughness/temp_keywords` folded at layers 7d/6
      by `continuous.recompute` and ended in the cleanup step, RULE 613.4d /
      514.2), `-1/-1` counters (`add_counters` now carries a counter `kind`),
      and `scry` (RULE 701.18, a legal keep-on-top scry that fires a `SCRY`
      event). Still open: regenerate, mode/"choose one", "up to N" targets
      — each needs a one-shot `GameEffect` + registry entry first; oracle-text
      *recognition* of replacement clauses (the binder is ready; a
      target/duration grammar for the front-end is not); parse-on-load
      memoization in `LazyCardLoader`; and *behaviour* for the remaining
      parametric keywords (alternative costs, combat maths).
- [~] Combat blocking + creature-vs-creature damage: **engine done** —
      `GameEngine.declare_blockers`/`can_block` and a rewritten
      `_step_combat_damage` handle blocked/unblocked attackers, gang blocks
      (lethal-first damage spread), and blockers striking back, with the
      SBA destroying lethal-damaged creatures. Attackers now declare a
      defender (player or opponent planeswalker, RULE 508.1a) and the solo
      goldfish gains a passive dummy so swings connect. Combat & evasion
      **keywords are done** (`game/combat.py` recognizes them off Scryfall
      `keywords` + oracle text; the engine honours them): flying/reach,
      menace, defender, haste, vigilance, first strike, double strike (two
      damage steps), deathtouch, trample, lifelink, indestructible, and
      protection-from (colour/creatures/everything). Keywords surface on the
      board as badges. Remaining: an *interactive* blocker-declaration UI
      (opponent-side, needs the multiplayer priority loop).
- [~] Static abilities / continuous-effects layer system (RULE 613):
      **engine done** — `game/continuous.py` re-derives every battlefield
      permanent's characteristics in layer order (2 control, 4 type-changing,
      5 colour, 6 ability-adding, 7a/7b/7c/7d/7e power/toughness), stamping
      derived P/T, added types and granted keywords plus a per-object layer
      *trace* onto each object; recomputed on every SBA pass and before the
      view. `StaticAbility` + registry now bridges **every** layer it
      implements: `anthem`/`pt_set`/`grant_keyword`/`type_change`/
      `cost_reduction` (as before) plus `color_change` (layer 5),
      `control_change` (layer 2), `pt_cda` (layer 7a) and `pt_switch`
      (layer 7e) — previously those four layers were only reachable by
      constructing a `StaticAbility` directly in a test fixture; a hand-
      authored/parsed `static` `AbilitySpec` had no whitelisted way to reach
      them. Granted keywords flow into combat; cost reductions/increases
      apply at cast time (RULE 601.2f). The goldfish UI has an optional,
      default-hidden layer/static panel. **`affects` gained
      `"attached_permanent"`**: resolves off the ability source's own
      `attached_to` (RULE 303.4/301.5), so an Aura/Equipment/Reconfigure's
      own static buff/keyword-grant/colour-change/control-change now actually
      lands on whatever it's attached to — this was the missing half of Aura/
      Equipment support (see the entry below); `control_change` +
      `"attached_permanent"` also covers Mind-Control-style "you control
      enchanted creature" Auras. Seed catalogue example: `Armadillo Cloak`
      (`ability_catalogue.py`). **Timestamp ordering** within a layer
      (`_in_layer` sorts by `GameObject.timestamp`, stamped on battlefield
      entry). **Layer 1 (copy effects, RULE 707) now has its "becomes a
      copy" half too** — see the dedicated entry below (`RulesEngine.
      become_copy`); it's modeled as a discrete mutation rather than a
      per-recompute layer (see that entry for why). Remaining, deliberately
      *not* built (evaluated 2026-07-09, see chat history): **layer 3**
      (text-changing effects, RULE 612) — audited the full ~1000-card cache
      (`cache/db/cards.db`) for anything needing it (Artificial Evolution-
      style word-swaps); zero hits, so there is nothing to build this
      against or test it with. **Full RULE 613.8 dependency ordering** —
      traced every effect type this engine has; every real interaction
      crosses *different* layers, which the fixed layer order (2→4→5→6→
      7a-e) already sequences correctly regardless of timestamps. Nothing
      in the current effect vocabulary can construct a same-layer
      dependency case, so a general dependency-graph algorithm here would
      be speculative and untestable. Revisit both if a card or a new effect
      type ever needs them. Tests: `test_continuous.py`,
      `test_effect_binder.py` (`TestStaticEffectRegistryBridges`).
- [x] Layer 6 ability-adding grant of a *non-keyword* ability (RULE 613.7f)
      — **done** (2026-07-09). Follow-up correction to the "layer 3" entry
      above: two real cards — Tyvar Kell ("Elves you control have '{T}: Add
      {B}.'") and Dionus, Elvish Archdruid ("Elves you control have '\<a
      triggered ability\>'") — were initially reported as needing layer 3
      (RULE 612 text-changing), citing CR 612.1's mention of text "granted …
      by other effects". That's wrong: RULE 613.1 puts ability-adding in
      layer 6, the same layer `grant_keyword` already used — these two just
      grant a mana ability / a full triggered ability instead of a bare
      keyword slug, not a text substitution. New `EffectSpec` types
      `grant_mana_ability` (`mana`, a `mana_options`-shaped list) and
      `grant_triggered_ability` (`trigger_event`, `grant_effects` — nested
      one-shot-effect specs through the same `EffectRegistry` whitelist,
      `once_per_turn`, `optional`, `controllers_turn_only`), docs/11 §6.
      `mana_abilities.mana_options_for(obj)` folds the grant onto the
      permanent's own printed options (`game_engine.py`'s 3 call sites
      switched to it). A granted *triggered* ability needs a genuinely new
      primitive: a stable instance per (granting ability, affected object)
      relationship (`GameState._granted_ability_cache`), rebuilt from cache
      every recompute rather than freshly constructed, so per-instance state
      — `TriggeredAbility.once_per_turn`/`_last_triggered_turn` (also new;
      RULE 603.2) — survives across passes; the cache is pruned back to only
      currently-valid relationships every pass, so the grant (and its turn-
      tracking) disappears the instant it stops applying, no separate
      removal code (RULE 613.6). Each grantee gets its *own* scoped instance
      (`continuous._granted_trigger_condition`, matched on the firing
      event's `instance_id`) — without it, e.g. tapping one Elf would
      incorrectly fire every other Elf's copy of the same granted ability
      too. Needed a real primitive that plain didn't exist: a `TAPPED` event
      (RULE 701.21b, "whenever ~ becomes tapped") — `RulesEngine.set_tapped`
      now fires it on a genuine untapped→tapped transition (never for a
      permanent entering already tapped, matching the real "becomes tapped"
      ruling), and the three call sites that used to tap a permanent via the
      bare `GameObject.tap()` (declare attackers, `tap_for_mana`,
      `activate_ability`'s tap cost) now go through it. `TapEffect` gained
      the same untargeted self-acting mode `AddCountersEffect` already had
      (`target_kind=None` → acts on the effect's own source, no player
      choice — "untap it" in Dionus's granted ability always means the
      specific Elf, never a target pick). Registered: `Tyvar Kell`,
      `Dionus, Elvish Archdruid` (`ability_catalogue.py`) — static clauses
      only; their loyalty abilities/emblem are a separate, unrelated gap
      (loyalty abilities in general are modeled; emblems aren't at all).
      Tests: `test_static_ability_grants.py`.
- [~] "Become a copy of target permanent" (RULE 706/707, layer 1) —
      **core mechanic done**. `RulesEngine.become_copy(obj, target,
      add_types, add_subtypes)` mutates `obj.card` in place to `target`'s
      copiable values (`Card.as_copy` — name, mana cost, colours, type/
      subtypes, rules text, P/T, loyalty; RULE 706.2) and clears + rebinds
      `obj`'s own catalogue-derived abilities/keywords from the new card
      (a copy gains the copied object's abilities, not its own) — everything
      RULE 706.2 doesn't cover (instance id, zone, owner, controller,
      counters, tapped state, attachments) is untouched, since none of it
      lives on `Card`. New `become_copy` `EffectSpec`/`BecomeCopyEffect`
      (docs/11 §5); registered real cards: `Clever Impersonator`,
      `Phantasmal Image` (`add_subtypes=["Illusion"]`), `Copy Artifact`
      (`add_types=["Enchantment"]`). Modeled as an ordinary
      `ENTERS_BATTLEFIELD` trigger rather than the true RULE 614.1c/614.12
      "as ~ enters" replacement timing (not wired — same gap as the
      conditional-tapland item above). **The "newly surfaced" targeting gap
      this uncovered is now fixed too** (see "Triggered-ability target
      choice" below) — these three cards are genuinely interactively
      playable end-to-end, including the "you may" decline, through the
      normal session `choose`/`decline` path. Tests: `test_card.py`
      (`TestAsCopy`), `test_ability_catalogue.py`, `test_game_engine.py`
      (`test_become_copy_*`), `test_trigger_targeting.py`.
- [x] Triggered-ability target choice (RULE 115 / 603.3c / 603.5) —
      **done**. A triggered ability's own targeting effect used to place
      blind (`_place_trigger` pushed a `TriggeredAbility` with no
      `targets` at all — the gap `become_copy` surfaced, above). Fixed
      generally, not just for `become_copy`: `put_triggers_on_stack` /
      `RulesEngine._place_triggers` now check each queued trigger's first
      targeting effect (`_trigger_target_spec`) and, if it has one, open a
      `trigger_target` `pending_choice` — one option per legal target,
      built the same `{"id","label","instance_id"?}` shape as search/
      cascade/discover/order_triggers, so the existing generic choice UI
      renders it with **zero frontend changes**. `resolve_trigger_target_
      choice` places the chosen target (or, for an optional/"you may"
      ability, honours a "decline" option) and resumes whatever else was
      queued behind it; a *required* target with no legal option at all
      never goes on the stack (RULE 603.3c), matching real rules exactly
      rather than resolving with an absent target. **Also covers RULE
      603.5 for a targetless "you may"** — previously `TriggeredAbility.
      optional` was carried but never consulted, so e.g. "you may draw a
      card" always just happened; now it opens a plain do/decline choice
      (`_trigger_may_choice`, the `"do"` sentinel `resolve_trigger_target_
      choice` recognizes) before placing. Wired into
      `GameEngine.resolve_pending_choice` (`kind == "trigger_target"`) —
      answered through the same session `choose`/`decline` action as every
      other pending choice. **Known narrow gap**: a trigger placed via the
      separate, opt-in RULE 603.3b interactive-ordering choice
      (`resolve_trigger_order_choice`) still places directly without a
      target-choice pause — combining manual trigger ordering with a
      targeted trigger among the ordered set isn't handled (both features
      are individually solid; the two together is untested/unhandled).
      Tests: `test_trigger_targeting.py`.
- [ ] Replacement-effect ordering by the affected player (RULE 616.1) —
      currently deterministic discovery order; needs a player prompt once
      interactive play does. (Trigger ordering, RULE 603.3b, is now
      interactive — see Done "Ordering choices".)
- [x] Trigger ordering *within* a controller (RULE 603.3b) — **done**.
      When `state.interactive_ordering` is on and the active player has two
      or more simultaneous triggers, `put_triggers_on_stack` opens an
      `order_triggers` `pending_choice`; `resolve_trigger_order_choice`
      places them in the chosen order (picked-first → placed-first →
      resolves-last). Off by default so solo goldfishing is unchanged.
      Tests: `test_ordering.py`.
- [x] Loyalty / planeswalker abilities (RULE 606) — **done (basic)**.
      `costs.ActivationCost.loyalty` (a signed `[±N]` cost, parsed by
      `_LOYALTY_RE` + the segmenter's `[±N]:` recognition); planeswalkers
      enter with printed starting loyalty (`Card.loyalty`, set in
      `add_to_battlefield`); `GameEngine._can_activate_loyalty` gates to
      sorcery speed + once-per-turn (`activated_loyalty_this_turn`, reset at
      untap); activation pays by changing loyalty counters; combat/other
      damage to a planeswalker removes loyalty (`deal_damage`); the 0-loyalty
      SBA (RULE 704.5i) sends it to the graveyard. Tests:
      `test_planeswalker.py`. Not yet: the specific chapter/loyalty *effects*
      beyond what the handler table already covers.
- [x] Aura / Equipment **attachment resolution** (RULE 303 auras, 301.5
      equipment, keyword `equip`/`fortify`/`reconfigure` RULE 702.6/67/151) —
      **done**. An Aura attaches to its cast-time target on resolution (RULE
      303.4f, `RulesEngine.resolve_top_of_stack`; fails to attach → straight
      to the graveyard); Equip/Fortify/Reconfigure are live sorcery-speed
      activated abilities (`effect_binder._keyword_activated_ability`,
      untapped/re-payable per RULE 301.5c/702.151b); targeting is restricted
      to what each can legally attach to (`targeting.legal_targets`,
      `RulesEngine._attachment_legal` — creatures for Equip/Reconfigure, the
      Aura's `enchant` quality otherwise). RULE 704.5m/n on the host leaving:
      an Aura goes to the graveyard, an Equipment/Fortification/Reconfigure
      permanent just becomes unattached and stays on the battlefield
      (`RulesEngine._detach_attachments_from`). RULE 702.151b: a Reconfigure
      permanent stops being a creature while attached and regains it the
      moment it's unattached (`GameObject._removed_types`, computed in
      `continuous.recompute`'s layer-4 pass). And the attached buff/keyword
      *does* now flow through the layer engine — see the layer-system entry
      above (`affects="attached_permanent"`). Tests: `test_game_engine.py`
      (aura/equipment/reconfigure attach+detach+buff tests),
      `test_continuous.py`. Remaining: re-validating an *existing* attachment's
      legality every SBA pass (RULE 704.5m/n also cover a target that stays on
      the battlefield but becomes illegal, e.g. by gaining protection — today
      only "host left the battlefield" is checked); update the Engine-Status
      tab (`implementationStatusView.js`) off "partial".
- [x] Commander tax (RULE 903.8) — **done**. `Player.commander_casts`
      (instance id → count) is incremented on a command-zone cast in
      `GameEngine.cast_spell`; `effective_cast_cost` adds `{2}` per previous
      cast via `commander_tax()`, floored generic, and surfaced in the cast
      action (`commander_tax`/`effective_cost`). The counter deep-copies with
      the player for rewind. Tests: `test_game_engine.py`
      `test_commander_tax_adds_two_per_previous_cast`.
- [x] Conditional enters-tapped choice (RULE 614.1 replacement) — **done**.
      `ability_catalogue.land_tap_condition(card)` classifies a land's
      tapped-entry clause off its oracle text: `"always"` (plain tap-land),
      `"never"` (no clause, or an unrecognized conditional shape — fails
      safe untapped), `"pay_life"` (shock lands: "you may pay N life. If
      you don't, ~ enters tapped."), `"unless_types"` (check lands: "unless
      you control a/an X [or a/an Y …]"), or `"unless_count"` (fast/slow
      lands: "unless you control N or fewer/more other lands").
      `RulesEngine.enter_land_tapped`, called from `GameEngine.play_land`,
      resolves the deterministic shapes immediately against the board the
      controller already has (evaluated before the land itself joins the
      battlefield, so "other lands" naturally excludes it); a shock land
      opens a genuine `land_tapped` `pending_choice` (tapped by default, as
      if declined) — `resolve_land_tapped_choice("pay")` pays the life
      (`RulesEngine.lose_life`) and flips it untapped, reusing the same
      `pending_choice`/`resolve_pending_choice` plumbing as search/cascade/
      trigger-target choices. Pain lands (no "enters tapped" text at all)
      and other unrecognized conditional shapes are untouched. Tests:
      `test_ability_catalogue.py`.

## Card-type & structural coverage (Backlog)

Card *kinds* the engine doesn't model as anything beyond a generic
permanent/spell. None block goldfishing a typical deck, but each is a
clause the future oracle parser (docs/09) or a dedicated handler must
eventually own. Roughly in decreasing commonness:

- [~] Double-faced & modal-DFC cards (RULE 712): **transform on the
      battlefield done** — `Card.back_face()` builds the back as its own
      `Card`, `GameObject.transform()`/`transformed` swaps faces reversibly
      (re-seeding a transforming planeswalker's loyalty), surfaced in
      `to_dict`. **Modal DFC back-face cast/play from hand (712.10) is now
      done too**: `RulesEngine.snapshot_face`/`restore_face`/`switch_to_face`
      (next to `become_copy`, same "clear + rebind catalogue-derived
      abilities" treatment) let `GameEngine.cast_spell`/`play_land` rebind
      an object onto its `is_modal_dfc` back face before the ordinary
      cast/play body runs unchanged; `can_cast`/`effective_cast_cost`/
      `can_play_land` gained a non-mutating `face="front"/"back"` preview
      (via `_face_card`) so `legal_actions`/`_cast_action` can offer *both*
      faces as independent actions for the same hand card without side
      effects, and a rejected back-face cast (e.g. no legal target) rolls
      back to the front face rather than sticking. Wired through
      `services/game_session.py` (`action["face"]`) and
      `frontend/src/js/gameBoardView.js` (a second button per MDFC hand
      card, keyed `instance_id:face` wherever DOM lookups could otherwise
      collide with the front's). Tests: `test_card_structures.py`.
      Remaining: a *transform trigger/effect* to call `GameObject.transform`,
      and the day/night (RULE 731) tie-in. MDFC commanders cast from the
      command zone are a known, deliberately unhandled edge case (only
      hand-cast offers both faces).
- [ ] Adventure cards (RULE 715) and Split/Fuse cards (RULE 709) — cast
      one half, the other stays available; recognised structurally
      (`Card.is_adventure`/`is_split`) but both still resolve as the single
      front-face spell.
- [~] Saga (RULE 714): **counter mechanics done** — a Saga enters with a
      lore counter (`add_to_battlefield`), gains one after its controller's
      draw step (`RulesEngine.advance_sagas`, called from `_step_draw`), and is
      sacrificed by an SBA at its final chapter (RULE 704.5x,
      `_saga_final_chapter` reads the roman-numeral markers). Remaining: the
      chapter *abilities* firing per lore counter. Class (716) / Leveler (711)
      not started. Tests: `test_card_structures.py`.
- [~] Copying objects (RULE 707): **token copies done** —
      `RulesEngine.copy_permanent` + the `copy_permanent` effect create a token
      clone of a target permanent's copiable card. Remaining: "becomes a copy
      of" as a layer-1 continuous effect (the layer-1 gap above).
- [ ] Battles (RULE 310) and Dungeons (RULE 309) — new type lines with
      their own attack/venture subsystems.
- [ ] Niche/format extras: Emblems (RULE 114), Stickers (RULE 123), the
      Monarch (RULE 725) / Initiative (RULE 726), Rad counters (RULE 728),
      and the remaining multiplayer/casual variants (CR 8, CR 9 beyond
      Commander). Deprioritized until a deck needs one.

## Game Engine (Phase 3) — remaining

- [~] Multiplayer game session + priority system (UC4): **priority
      primitive built; session wiring remains**. `GameEngine.pass_priority`
      now takes an optional `player`: called with one (RULE 117.3-4) it only
      resolves the top of the stack once every living player has passed in
      succession, hands priority to the next player (APNAP, `_advance_priority`)
      otherwise, and any real action reclaims priority (`give_priority`, called
      from `begin_turn`/`_run_step`/`play_land`/`cast_spell`/`activate_ability`).
      `GameState.priority_passed` tracks who has passed and deep-copies for
      rewind. Called with no `player` it keeps the old solo/goldfish
      auto-resolve, so nothing regresses. Tests: `test_priority.py`. Still
      **stubbed**: `GameSessionManager.create_multiplayer` raises
      `MultiplayerNotImplementedError` and `POST /api/game/multiplayer` returns
      501 — the session/route need to drive `pass_priority(player)` and expose
      the priority holder, and interactive blocker declaration
      (`declare_blockers`, engine-ready) needs the opponent-side UI.
- [ ] Wire the `WebSocket /ws/game/{game_id}` handler (`api/game_ws.py`)
      into a server-held session: it's still the transport-only relay,
      not feeding actions into `GameEngine`. Solo play uses the REST
      session API (fine for one player); the WebSocket becomes necessary
      for multiplayer (pushing an opponent's moves). Swap its
      `_broadcast_action` stand-in for "run the action through the
      session/engine, broadcast `GameState.to_dict()`".

## LLM Deck Analysis (UC2)

- [ ] `POST /api/decks/{id}/analyze`: Claude API integration, prompt
      templates, structured output parsing, caching (docs/02 UC2,
      docs/04 Phase 6). `Deck.analysis_id` is already reserved to link a
      saved deck to whatever this produces — no `Analysis` model/table
      exists yet, design that alongside this endpoint rather than
      assuming the reserved field's shape is final.

## Auth & persistence

- [ ] User accounts, login/signup (docs/04 PART 4 REST endpoints).
- [ ] No user accounts yet, so saved decks aren't scoped to an owner —
      anyone hitting the API sees every saved deck. Revisit once auth
      exists.
- [ ] Game history / session persistence.

## Bot AI (UC5)

- [ ] Greedy bot strategy (docs/02 UC5) — a start exists in
      `GameEngine.run_goldfish_turn`/`auto_play_step` (play a land, tap
      out, cast cheapest-first, swing); a real bot would weigh lines.

## Import — follow-up from the frontend

- [ ] Server-side Moxfield import proxy
      (`GET /api/import/moxfield/{deckId}`), tried client-side and
      reverted (see `../frontend/ToDo_Frontend.md` "Import — follow-ups"):
      Moxfield's Cloudflare protection returned HTTP 403 on every
      plain request tried by hand, including from a browser origin.
      A server-side fetch removes the browser-CORS obstacle but still
      isn't guaranteed to get past bot protection — may need
      browser-like request headers or a headless-browser fallback.
