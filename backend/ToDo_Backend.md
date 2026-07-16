# Backend TODO

Open backend items only — **when an item is finished, move its narrative
into the matching section of
[Done_Backend.md](../docs/implementation-state/Done_Backend.md) (section
headers here mirror there) instead of leaving it `[x]` in place.** This file
is read in full fairly often (by humans and Claude); a `[x]` entry with a
full writeup left behind defeats the split and re-bloats every future read.
A one-line "moved to Done_Backend.md, section name" pointer, or just
deleting the line outright, is enough — the ToDo/Done split only pays off if
it's kept up, see CLAUDE.md "Conventions & gotchas".
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
      event).
      **2026-07-14 — three waves of parser expansion (cache-wide coverage
      16.9% → 26.9% fully-MODELED, suite 922 → 1027 tests):**
      - **Enters-tapped claiming** (RULE 614.1): tap-condition recognition
        moved to pure `parser/oracle/catalogue/lands.py`
        (`tap_clause_condition` full-matches one line; `game/
        ability_catalogue.land_tap_condition` now delegates), the gate
        claims recognized lines covered-without-spec, and two new engine
        kinds landed — `unless_opponents` (Battlebond lands) and
        basic-land `unless_count` (`test_oracle_lands.py`,
        `test_land_tap_conditions.py`).
      - **Attached-permanent statics**: "equipped/enchanted/fortified …
        gets +N/+N [and has \<kw\>]" / "… has \<kw\>" parse to `anthem`/
        `grant_keyword` with `affects="attached_permanent"` (engine side
        already existed; `test_oracle_statics.py`).
      - **Trigger-condition scoping** (RULE 603.1): the segmenter now
        emits `trigger.condition` ({subject: self} or {subject: group,
        type/controller/other}), ENTERS_BATTLEFIELD/DIES/ATTACKS/BLOCKS
        events carry `instance_id`+`object_types`, and the binder builds
        the matching predicates — fixing a live over-firing bug where a
        parsed "when ~ enters" fired for *any* entering permanent
        (`test_oracle_triggers.py`).
      - **Counter family**: spell target filters (noncreature / card-type
        list / mana-value on `TargetSpec.spell_filter`), "unless its
        controller pays {…}" via a `counter_unless_pays` `pending_choice`
        (auto-counter when unpayable), and "this spell can't be countered"
        as a `CantBeCounteredEffect` marker `RulesEngine.counter_spell`
        refuses (`test_counter_family.py`).
      - **Modal spells** (RULE 700.2): "choose one —"/"choose one or
        both —" blocks parse into `AbilitySpec.modes`
        (`catalogue/modal.py`); casting offers one `cast_spell` action per
        mode (the MDFC per-face pattern), the chosen mode's effects
        becoming the spell's resolve-time effects (`test_modal_spells.py`).
      - **Additional cast costs** (RULE 601.2b/601.2h): "as an additional
        cost …, sacrifice a creature/artifact/land | discard a card |
        pay N/X life" parse onto `AbilitySpec.additional_cost`, gate cast
        legality, and are paid at cast time (survive a counter); reuses
        `costs.parse_activation_cost` (`test_additional_costs.py`).
      - **New one-shot families**: return-to-hand (bounce), graveyard
        recursion (new `graveyard_creature` / `creature_you_control` /
        `land_you_control` target kinds), tutor-to-hand + basic-land
        fetch (onto the existing `search`), `add_mana` (Dark Ritual),
        mass damage ("deals N damage to each creature/player/opponent",
        a closed `selector` on `DealDamageEffect`), and ETB self-attach
        for Equipment (`test_effect_families_wave3.py`).
      Regenerate (RULE 701.16) is done — moved to Done_Backend.md "M1 —
      Oracle-effect parser".
      "Up to one" targets (RULE 115.1a, N=1 only), the "if this spell was
      kicked, \<effect\>." additional-effect conditional (RULE 702.33b), and
      oracle-text recognition of three of the five registered replacement
      families (`double_tokens`/`double_counters`/`additional_damage`) are
      **done** — moved to Done_Backend.md "M1 — Oracle-effect parser"
      (2026-07-16 "Batch 11" entry).
      Still open: a real "up to two/three/N"/"up to X" **multi**-target
      choice (N>=2 — needs an interactive multi-select and per-effect
      application over a *list* of targets, a materially larger feature
      than the N=1 case just shipped); "add 1 mana of any color" (a mana
      *choice*); `prevent_damage`'s two real cards (Riot Control/Thought
      Lash) — a *one-shot spell effect* that grants a temporary shield
      (Regenerate-shaped: a new effect class + `RulesEngine` method), not
      the standing-permanent replacement-clause shape the other three
      families used; a differently-scoped counter-doubling clause
      (Innkeeper's Talent's "on a permanent or player") and a compound
      colour/type filter (Mechanized Warfare's "a red or artifact source")
      — both fail closed today, deliberately not guessed; the full RULE
      616.1 "if X would Y, Z instead" grammar beyond those five fixed
      sentences (many more real formulations — target/duration variants);
      and the remaining processing-list tail (run `parser/oracle/
      processing_list.coverage_over_cards` for the current ranking —
      top blockers now: "choose \<n\> —"/"choose \<n\> or more —" (a
      larger modal-header grammar than RULE 700.2's "choose one"/"choose
      one or both" — a genuinely bigger feature than the N=1 "up to one
      target" case shipped in Batch 11: an interactive multi-*mode*
      selection, not a target choice), "you may look at the top card of
      your library any time" (a standing *permission* — the underlying
      **engine capability now exists** as of 2026-07-16
      [`game/top_library.py`, moved to Done_Backend.md "Rules Engine
      (Phase 2)"], hand-authored for its two real cards already in the
      local cache, Oracle of Mul Daya and Glarb, Calamity's Augur — but
      this processing-list template still shows all 13, unmoved, since
      `coverage_over_cards()` runs the oracle-text *parser* only and has
      no way to know about the hand-authored registry; closing this
      template for real needs the parser's own front-end recognition of
      the clause, a separate follow-up), monarch/initiative (deferred per
      M6), prohibition/cost-modification statics, and emblems).
      Parse-on-load memoization (`parser/oracle/gate.py`) and surveil
      (RULE 701.31) are **done** — moved to Done_Backend.md "M1 —
      Oracle-effect parser" (2026-07-16 "Batch 12" entry), which also
      fixed a real latent bug found along the way: Class's (RULE 716.3)
      level-header regex assumed "Level N: \<cost\>", but every real
      Class card prints the cost *first* ("\<cost\>: Level N") — the old
      regex had never matched a single real card, only the (also
      backwards) hand-written test fixtures that happened to agree with
      it.
      **Mana-ability costs/production redone (RULE 605.1a/602.1)** — moved
      to [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)" (2026-07-15 entry). Verified against the Elf
      mana-dork family; still open from that pass:
      - Mana *spend* restrictions ("Spend this mana only to cast an Elf
        creature spell/a creature spell", Gnarlroot Trapper/Beastcaller
        Savant) are **done** for the creature/legendary/commander/instant-
        or-sorcery/named-creature-type/contains-{X} shapes (moved to
        Done_Backend.md, "Rules Engine (Phase 2)", 2026-07-16 entry) — a
        land's own "spend only on a spell of the *chosen* creature
        type/color" variant (Cavern of Souls, Unclaimed Territory, Throne
        of Eldraine) and a mana-value-threshold clause (Helga, Troyan)
        remain unrecognized (fail-soft, same as before this batch).
      - "Add N mana **in any combination of colors**" (Flamebraider/Gwenna/
        Smokebraider's fixed "two", Selvala's variable "X" = the greatest
        power among creatures you control) is **done** (moved to
        Done_Backend.md, "Rules Engine (Phase 2)", 2026-07-16 entry) —
        `ManaAbility.any_combination` + `GameEngine.tap_for_mana`'s
        ``color_split`` parameter; no split-choice UI exists yet
        (frontend/ToDo_Frontend.md), so today's board still offers a
        single-colour default per the pre-existing options list.
      - Hand-zone mana abilities ("Exile this card from your hand: Add
        …" — Elvish/Simian Spirit Guide) are **done** (moved to
        Done_Backend.md, "Rules Engine (Phase 2)", 2026-07-16 entry) —
        `hand_mana_abilities`/`hand_mana_abilities_for` +
        `GameEngine.activate_hand_mana_ability`, a new `activate_hand_mana`
        legal-action kind wired through `game_session.py`; no frontend UI
        for it yet (`frontend/ToDo_Frontend.md`).
      - A Leveler's mana ability is now level-gated (moved to
        Done_Backend.md, "Rules Engine (Phase 2)", 2026-07-16 entry) —
        `game/mana_abilities.py` tags a tier's own mana ability with that
        tier's `min_level`/`max_level` and `mana_abilities_for` filters by
        the object's current `level` counter, the same gate
        `continuous.py` already applied to *static* Leveler tiers.
      - Deathrite Shaman is **done** (moved to Done_Backend.md, "Rules
        Engine (Phase 2)", 2026-07-16 entry) — all three abilities now
        parse and resolve end to end via the generalized graveyard-card
        targeting family (`game/targeting.py`'s `_GRAVEYARD_TARGET_KINDS`)
        plus the 2026-07-16 "add one mana of any colour" primitive.
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
      entry). **Layer 1, 3, and RULE 613.8 dependency ordering are now
      built too** (2026-07-14, reopening the 2026-07-09 "deliberately not
      built" decision below at the user's request — see the entries for
      "become a copy of target permanent" and RULE 613.8 dependency
      ordering for what changed and why each was scoped the way it was):
      **layer 3** (text-changing, RULE 612) is scoped to word-substitution
      over a new `GameObject.effective_oracle_text` derived field
      (`continuous.py`'s `text` sublayer, between layers 2 and 4), consumed
      today only by `combat.protections_of_text` (the canonical Artificial-
      Evolution "protection from red" → "protection from blue" case) — not
      a full oracle-text re-parse, so bound abilities/keywords are
      unaffected; no real card exercises it yet (a synthetic direct-
      `StaticAbility`-construction test suite covers it, the same bootstrap
      pattern `pt_cda`/`pt_switch` used before real-card coverage existed).
      **RULE 613.8 dependency ordering** is bounded to layer 2
      (`_order_control_effects`): traced every selector this engine has
      that could construct a same-sublayer dependency — a `pt_cda`'s
      count-selectors (`_count_selector`) can only *count* objects, never
      read another object's power/toughness, so 7a is genuinely impossible,
      not just unauthored; layer 2's controller-scoped `affects`
      ("creatures you control") is the one real case (the textbook CR 613.8
      example — two control-changing effects where the second's scope
      depends on what the first stole), so direct-scoped abilities
      (self/attached_permanent) always apply before controller-scoped ones
      now, regardless of timestamp; every other sublayer is provably safe
      to leave on pure timestamp order. Tests: `test_continuous.py`,
      `test_effect_binder.py` (`TestStaticEffectRegistryBridges`).

      "Become a copy of target permanent/creature" (RULE 706/707, incl. the
      layer-1 continuous form) shipped — moved to
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)".

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

      Copying objects (RULE 707, token copies + "becomes a copy of") shipped
      — moved to
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Card-type & structural coverage".
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
      