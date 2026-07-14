# Backend TODO

Open backend items. Completed work has moved to
[Done_Backend.md](../docs/implementation-state/Done_Backend.md) (section
headers there mirror these).
See [../docs/implementation-state/10_COMPLETION_ROADMAP.md](../docs/implementation-state/10_COMPLETION_ROADMAP.md)
for the dependency-ordered plan to finish the implementation. The original
Weeks 1–4 roadmap is archived at
[../docs/implementation-state/history/IMPLEMENTATION_STATUS.md](../docs/implementation-state/history/IMPLEMENTATION_STATUS.md).

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
      this uncovered is now fixed too** (`docs/implementation-state/
      Done_Backend.md` "Triggered-ability target choice") — these three
      cards are genuinely interactively playable end-to-end, including the
      "you may" decline, through the normal session `choose`/`decline`
      path. Tests: `test_card.py` (`TestAsCopy`), `test_ability_catalogue.py`,
      `test_game_engine.py` (`test_become_copy_*`), `test_trigger_targeting.py`.

## Card-type & structural coverage (Backlog)

Card *kinds* the engine doesn't model as anything beyond a generic
permanent/spell. None block goldfishing a typical deck, but each is a
clause the future oracle parser (docs/09) or a dedicated handler must
eventually own. Roughly in decreasing commonness:

- [~] Double-faced & modal-DFC cards (RULE 712): **transform on the
      battlefield, modal-DFC back-face cast/play, a generic transform
      trigger/effect, and day/night (RULE 731) + daybound/nightbound (RULE
      702.145) are all done** — see `docs/implementation-state/
      Done_Backend.md` "Card-type & structural coverage". Remaining:
      bespoke *conditional* transform triggers ("look at the top card…, if
      instant/sorcery, transform" — Delver of Secrets) aren't modeled (a
      genuinely new "reveal + conditional" one-shot family); the legacy
      pre-2021 non-daybound werewolf template ("if no spells were cast last
      turn, transform ~") is deliberately not modeled, superseded by RULE
      731; and MDFC commanders cast from the command zone are a known,
      deliberately unhandled edge case (only hand-cast offers both faces).
- [ ] Saga (RULE 714) / Class (RULE 716) / Leveler (RULE 711) residual
      edges — the mechanics themselves are done (`docs/implementation-state/
      Done_Backend.md` "Card-type & structural coverage"); these are left
      `UNMODELED`/fail-closed rather than guessed: a Class level combining
      both a static "cumulative" grant and a separate one-shot "when this
      Class becomes level N" trigger in the same block; a level-block body
      using a trigger phrase/effect family the oracle parser doesn't
      already recognize (independent of this work — e.g. "creature deals
      combat damage to a player"); CDA-based Leveler P/T (``*/*``, no card
      in the pool needs it); a Leveler's rare non-keyword *base*
      (pre-`LEVEL`) ability line (parsed ungated).
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
      