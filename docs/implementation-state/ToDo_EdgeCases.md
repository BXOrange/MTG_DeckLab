# Edge Cases — cross-cutting registry

A consolidated index of **narrow, deliberately-unhandled edge cases**: specific,
low-probability scenarios the code or docs explicitly call out as consciously
left unmodeled, simplified, or deferred — as opposed to a large open feature
(kicker/buyback costs, LLM deck analysis, multiplayer session wiring, …),
which stays in [`backend/ToDo_Backend.md`](../../backend/ToDo_Backend.md) /
[`frontend/ToDo_Frontend.md`](../../frontend/ToDo_Frontend.md) instead. The
line: if fixing it means designing a new feature, it belongs in a ToDo file;
if it means tightening an already-shipped feature's rough edge, it belongs
here.

Most of these are also mentioned in situ — next to the shipped feature they're
a rough edge of, in `ToDo_Backend.md` or
[`Done_Backend.md`](Done_Backend.md) — this file doesn't replace that
context, it's the place to check "is this a known gap?" without reading
every feature's full writeup. When an edge case gets fixed, delete its entry
here (and update wherever else it's mentioned) rather than marking it done in
place — like the other ToDo files, this one is meant to be read in full
occasionally, so it should only ever hold what's still true.

None of these block goldfishing a typical deck; each is here so the next
person who hits one of these scenarios finds a "yes, known, here's why"
instead of re-discovering it as a surprise bug.

## Targeting / protection / hexproof / ward

- **Hexproof-from-`<quality>` collapses to blanket hexproof.** RULE 702.11b's
  "Hexproof from red" is aliased onto the plain `hexproof` slug — a
  `FLAG`-shaped catalogue row, not `QUALITY`-shaped like `Protection` — so
  the "from X" scope is lost and the permanent is treated as hexproof from
  *everything*. Safe/overprotective (never lets an illegal target through),
  never rules-illegal, just not accurate. Fix: give `Hexproof` a `QUALITY`
  shape and regex like `Protection`'s.
  (`parser/oracle/catalogue/keywords.py`'s `_ALIASES`.)

- **An existing attachment's legality isn't re-validated every SBA pass.**
  RULE 704.5m/n also cover a target that stays on the battlefield but
  becomes newly illegal for the attachment (e.g. an enchanted creature gains
  protection after the Aura is already attached) — today only "the host left
  the battlefield" is checked, not an ongoing per-pass legality re-check.
  (`RulesEngine._detach_attachments_from`, `game/rules_engine.py`.)

- **`SacrificeEffect` auto-picks which permanent is sacrificed.**
  Annihilator's "defending player sacrifices N permanents" (RULE 702.86)
  uses the same non-interactive MVP auto-choice as
  `GameEngine._sacrifice_candidate` (cost-payment sacrifice) rather than
  letting the player choose. An interactive picker is a future upgrade.
  (`SacrificeEffect`, `game/effects.py`.)

- **`CopyPermanentEffect` doesn't model copy-of-a-copy.** RULE 707.2's
  "copiable values" interacting with *other* copy effects (a copy of a copy,
  layered copy effects) isn't modeled — it copies straight from the printed
  card. (`CopyPermanentEffect`, `game/effects.py`.)

- **A token copy via `create_token` never offers its own `enter_as_copy`
  choice.** Unlike `resolve_top_of_stack`'s `_resolve_permanent_spell`, a
  token created with RULE 614.1c/614.12 `enter_as_copy_effects` bound to it
  (a token copy of e.g. Clever Impersonator) never gets that choice offered
  mid-`create_token` — pausing mid-loop for "a copy of a copy-effect
  creature" is real complexity no card in the pool currently needs.
  (`RulesEngine.create_token`, `game/rules_engine.py`.)

## Layers / static abilities (RULE 613)

- **Layer 3 (RULE 612 text-changing) is scoped to one consumer.** Built, but
  only as word-substitution over a derived `GameObject.effective_oracle_text`
  field, consumed *only* by `combat.protections_of_text` (the canonical
  Artificial Evolution "protection from red" → "protection from blue" case)
  — not a full oracle-text re-parse, so bound abilities/keywords are
  unaffected by a layer-3 rewrite. No real card exercises it yet; a
  synthetic direct-`StaticAbility` test suite covers it.
  (`continuous.py`'s `text` sublayer, between layers 2 and 4.)

- **RULE 613.8 dependency ordering is bounded to one sublayer.** Only layer
  2's controller-scoped `affects` ("creatures you control") is ordered by
  dependency — the textbook CR 613.8 example (two control-changing effects,
  the second's scope depending on what the first stole). Every other
  sublayer is provably safe on pure timestamp order given the current effect
  vocabulary (e.g. a `pt_cda`'s count-selectors can only *count* objects,
  never read another object's P/T, so a layer-7a dependency is genuinely
  impossible with today's selectors, not just unauthored).
  (`continuous._order_control_effects`.)

- **Layer 1 "become a copy" mutates in place instead of running as a
  recompute pass.** `become_copy` (the permanent-ETB-copy mechanism, e.g.
  Clever Impersonator) directly mutates the object; only the *conditional*
  copy case (Vesuvan Shapeshifter) got the true per-`recompute` layer-1
  treatment. (`game/copy_mechanics.py`, `game/continuous.py`.)

- **A conditional layer-1 copy never reverts.** Per the real Vesuvan
  Shapeshifter ruling this is intentional, not a gap: once it locks onto a
  creature with no equivalent ability, it stays that way permanently — there
  is deliberately no "ability disappeared → revert" branch, even if the
  copy's own triggering condition later becomes false again.
  (`continuous._apply_copy_layer`.)

- **A granted trigger with no `instance_id` in its firing event isn't
  identity-scoped.** A layer-6-granted triggered ability (e.g. Dionus,
  Elvish Archdruid's "Elves you control have...") is scoped per-grantee by
  the firing event's `instance_id`, so one Elf's trigger doesn't fire for
  every other Elf — but an event shape carrying no `instance_id` at all
  isn't filtered by identity. Acceptable only because no card in the pool
  currently grants a trigger off such an event.
  (`continuous._granted_trigger_condition`.)

## Equipment / Auras / "combat damage to a player" triggers

The "Wyleth Equip" Boros voltron commander deck (`game/ability_catalogue.py`'s
Wyleth/Akiri/Bruenor/Sword-cycle/Sunforger/etc. block) motivated a new
`"attached_permanent"`/`"self_or_attached_permanent"` trigger-subject family
and a `EventType.DAMAGE` `"filter"` predicate (`effect_binder.
_trigger_condition`) for "whenever equipped creature deals combat damage to
a player" — both generic and reusable, but several individual cards in that
same batch hit older, still-open engine limits instead of new ones:

- **Two independent targets on one ability aren't supported** (docs/
  Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md §5) — Brass Squire's
  "attach target Equipment to target creature" and Halvar, God of Battle's
  "attach target Aura/Equipment attached to a creature you control to target
  creature you control" are both left unregistered/unmodeled rather than
  guessed at for this reason (`ability_catalogue.py`'s Halvar entry notes
  it; Brass Squire isn't registered at all, so it plays as a vanilla
  creature with whatever the RULE 702 keyword catalogue gives it).
- **Simian Sling's "defending player" resolves off its own combat-defender
  stamp**, which is only set when Simian Sling *itself* is the attacker —
  reconfigured onto a different attacking creature, the trigger still
  fires but finds no defending player to hit (`effects.
  _defending_player_of`, `ability_catalogue._simian_sling`).
- **A per-firing dynamic reference to "that creature"/"the token this
  effect just created" has no generic `TriggeredAbility` IR support.**
  `RulesEngine.check_rampage`/`check_ward` do this via a bespoke "construct
  a fresh `TriggeredAbility` per firing" pattern (`TriggeredAbility`'s own
  docstring spells it out); nothing generic exists. Kaldra Compleat's
  granted "exile that creature" and Sigarda's Aid's "whenever an Equipment
  you control enters, you may attach *it*" both hit this wall. (The same
  reflexive-trigger gap blocks several cube cards — see "cEDH staples
  cube".)
- **A few small, still-open extensions of shipped mechanics:** Embercleave's
  "costs {1} less for each attacking creature you control" needs a
  board-count-*during-declare-attackers* `count_selector` on the (existing)
  `self_cost_reduction_for`; Timely Ward's "cast as though it had flash if
  it targets a commander" needs a `"targets_a_commander"` key added to
  `conditional_flash`'s condition whitelist (`game/condition_query.py`).

## Card-type structures (DFC / Saga / Class / Leveler / Adventure / Prepared)

- **MDFC commanders cast from the command zone don't offer both faces.**
  Only a hand-cast MDFC does; a known, deliberately unhandled edge case.
  (`GameEngine._face_card`/`can_cast`/`cast_spell`, `game/game_engine.py`.)

- **Bespoke conditional transform triggers aren't modeled.** Delver of
  Secrets-style "look at the top card of your library, if it's an
  instant/sorcery card, transform ~" needs a genuinely new "reveal +
  conditional" one-shot family that doesn't exist yet.

- **The legacy pre-2021 non-daybound werewolf template isn't modeled.**
  "At the beginning of each upkeep, if no spells were cast last turn,
  transform ~" — deliberately not built, since RULE 731 (day/night)
  superseded this per-card template and only the new mechanic is built.

- **A Class level combining a static "cumulative" grant with its own
  separate one-shot "becomes level N" trigger in the same block** is left
  `UNMODELED`/fail-closed rather than guessed at.
  (`parser/oracle/catalogue/levels.py`, `gate.parse_oracle`.)

- **A level-block body using a trigger phrase/effect family the oracle
  parser doesn't already recognize** just hits the parser's general coverage
  gap — independent of the Class/Leveler feature itself (e.g. "creature
  deals combat damage to a player" inside a level tier).

- **CDA-based Leveler P/T (`*/*`) isn't modeled.** No card in the current
  pool needs it, so it fails closed rather than being guessed.
  (`gate.py`'s `_process_leveler_body`.)

- **A Leveler's rare non-keyword base (pre-`LEVEL`) ability line is parsed
  "ungated."** Any base-text ability line that isn't the recognized
  keyword-line/P/T shape parses without a level gate applied.
  (`parser/oracle/catalogue/levels.py`.)

- **Prepared cards: trigger-condition recognition limited to four base
  events.** A Prepared card's own "become prepared" condition only binds if
  it's one of the already-recognized trigger conditions (enters/dies/
  attacks/blocks) — a general parser gap, not specific to Prepared, but
  explicitly out of scope for that feature's ship.
  (`segmenter.py`'s `_TRIGGER_EVENTS`.)

- **Face-down permanent states (morph/manifest) aren't modeled**, so the
  goldfish/Replay board's card-back-sleeve fallback for a face-down token
  with no uploaded art currently has no real trigger condition to fire on —
  real transformed DFCs keep their genuine Scryfall back-face art instead.
  (`gameBoardView.js`'s `resolveImageUrl`; see also `CLAUDE.md` "What this
  is".)

## Casting / costs

- **`{E}` (energy) pips in cost text are silently ignored**, not modeled as
  the energy-counter mechanic. (`costs.parse_activation_cost`,
  `game/costs.py`.)

- **"Add 1 mana of any color" is left unclaimed.** The mana-symbol-run
  handler only claims a *pure* run of `{colour}` symbols (fail-closed) —
  which color is a player choice the parser doesn't yet express, so this is
  deliberately left unclaimed rather than guessed at.
  (`parser/oracle/catalogue/handlers.py`'s `_add_mana`/`_ADD_MANA_RE`.)

## Multiplayer / priority / trigger ordering

- **Manual trigger-ordering combined with a targeted/optional trigger in the
  same ordered set isn't handled.** A trigger placed via the opt-in RULE
  603.3b interactive-ordering choice (`resolve_trigger_order_choice`) is
  placed directly and does not pause for its own target/"you may" choice.
  Both features work individually; only the combination is untested/
  unhandled. (`RulesEngine._place_triggers`.)

## Data / cache freshness

- **A stale cached row (pre-`mana_cost_string`) keeps lossy mana-cost data
  until refetched.** Priced from the legacy flat pip tally +
  `converted_mana_cost` via `ManaCost.from_card` — correct total/colors, but
  hybrid/Phyrexian nuance stays unavailable for that row until the
  self-healing refetch (`Card.has_mana_cost_data`) happens to hit it.
  (`models/mana_cost.py`, `services/lazy_card_loader.py`.)

- **The commander ban list is hand-maintained, not live-sourced.**
  Scryfall's per-printing `legalities` field isn't fetched, so there's no
  live source for bans — deliberately conservative (only long-standing
  entries that survived unban waves), needs manual updates against the
  official banned-list page. (`services/commander_legality.py`'s
  `BANNED_COMMANDER_CARDS`.)

- **Commander legality doesn't yet recognize Background/"Friends forever"
  pairing, or enforce that a commander must actually be legendary.**
  `check_commander_legality` checks color identity, the ban list, and plain
  Partner/"Partner with X" pairing only. (`services/commander_legality.py`.)

## cEDH staples cube

Cards from a cEDH cube pool left `UNMODELED`/unregistered, grouped by the one
engine primitive each is blocked on (a card appears once, under its blocker).
Each is a specific gap, not a vague "too hard".

- **Two independent targeting effects on one ability** (docs/Reference/
  11_CARD_CATALOGUE_AUTHORING_GUIDE.md §5, "at most one targeting effect per
  `AbilitySpec`"): Archdruid's Charm's third mode (also a *dynamic* damage
  amount tied to the other effect's target), Brass Squire, Halvar God of
  Battle.
- **Dynamically-created one-shot delayed trigger (RULE 603.7)** — DONE
  (Batch 22, `GameState.delayed_triggers` + `create_delayed_trigger` effect,
  fired at STEP_BEGIN by `GameEngine._fire_delayed_triggers`; ``scope``
  controller/any, ``capture="target_mana_value"``, ``min_turn_offset``).
  **Mana Drain** now fully modeled (was counter-only). Still blocked on a
  *second* gap: Summoner's Pact / Pact of Negation need an interactive
  "pay {cost} or lose the game" choice at the delayed step; Corpse Dance needs
  Buyback + reanimation + a baked delayed-exile target.
- **Reflexive / per-firing dynamic-object trigger** — DONE (Batch 16,
  `TriggeredAbility.reflexive`): a trigger whose single targeting effect acts
  on the exact object that fired the event (found by the event's
  ``instance_id`` at placement time, no target choice), the generic form of
  the `check_ward`/`check_rampage` per-firing reference. The cards that need
  it each still carry a *second* blocker, so none is registered yet: Lavinia
  Azorius Renegade / Boromir Warden of the Tower need "if no mana was spent to
  cast it" mana-spent tracking (plus Lavinia's dynamic cast-prohibition,
  Boromir's Ring); Price of Glory is now DONE (Batch 20 added the per-tap mana
  event below, so it plays); Hope of Ghirapur needs "who was dealt combat
  damage by ~ this turn" history; Cloudstone
  Curio needs a "return another permanent you control that shares a type" choice.
- **Spell-copy mechanism** — DONE (Batch 17, `RulesEngine.copy_spell` +
  `copy_spell` effect, RULE 707.10): copies a stack spell as a copier-controlled
  token above the original, keeping its targets/{X}. Dualcaster Mage and Flare
  of Duplication (alt-cast dropped) now play. Still blocked on *other* gaps:
  Reiterate (Buyback alt-cost), Wandering Archaic (interactive per-opponent
  "may pay {2}" + reflexive copy), Narset's Reversal (needs a bounce-spell-to-hand
  effect alongside the copy). Magecraft's "or copy" firing condition unblocked.
- **Distinguishable per-tap mana-production event** — DONE (Batch 20,
  `EventType.TAPPED_FOR_MANA`): `GameEngine.tap_for_mana` fires a per-tap
  event after the mana lands in the pool (carrying the source's
  ``instance_id``/``object_types``/``controller_id``/``produced``), off a
  genuine mana-ability tap only. **Price of Glory** now plays — it composes
  this with the new `not_controllers_turn` intervening-if
  (`effect_binder._trigger_condition`, "if it's not that player's turn")
  and the batch-16 reflexive "destroy that land". Still blocked on a *second*
  gap each: Kinnan Bonder Prodigy needs "add one mana of any type that
  permanent produced" (a dynamic produced-mana amount); Wild Growth is a
  *triggered mana ability* (RULE 605.1b/605.4 — must resolve immediately into
  the pool, not via the stack, so its extra {G} is spendable in the same
  payment); Mana Web taps *all* the player's lands that could make matching
  mana.
- **Layer-6 grant of an *activated* ability** — only `grant_triggered_
  ability`/`grant_mana_ability`/`grant_keyword` exist: Umbral Mantle,
  Squirrel Nest.
- **Divided-damage primitive** — DONE (Batch 19, `DealDamageEffect(divided=
  True)`, RULE 601.2d): the total pool (typically {X}) is split across the
  chosen targets, ``double_at`` doubling it at a threshold (Shatterskull's
  X>=6). Fire Covenant (with the Toxic-Deluge `pay_life: "x"` cost) and
  Shatterskull Smashing (the sorcery front of the MDFC) now play. The "as you
  choose" split defaults to an even distribution (a UI-less simplification —
  total dealt and which permanents take it are exact).
- **Second dynamic-value source from a sacrificed permanent** — `StackItem.x`
  only threads a spell's announced `{X}`; nothing stashes an additional
  cost's sacrificed permanent (or its MV) for a resolving effect to read:
  Eldritch Evolution, Neoform.
- **"Choose a card name" input + dig-until-match loop** — no primitive lets a
  player name an arbitrary card before a zone is examined, nor exiles from
  the top until a filter matches: Demonic Consultation, Possibility Storm
  (also needs to intercept every player's every hand-cast), Tibalt's Trickery.
- **Random-number primitive** — DONE (Batch 21, `RulesEngine.random_int`/
  `random_choice`/`coin_flip`, RULE 705/706): reproducible from
  `GameState`'s ``(rng_seed, rng_counter)`` so it survives clone/undo. No cube
  card registered on it — Tibalt's Trickery pairs the random 1/2/3 with a
  dig-until-a-differently-named-nonland-card-then-cast-it-free mechanic, and
  Wheel of Misfortune needs a *secret simultaneous* number choice from every
  player (hidden multiplayer info) — both far beyond a random draw. Primitive
  proven directly, ready for a future coin-flip/Krark-style card.
- **Control-*exchange* primitive** — `control_change` (layer-2 static) and
  `CopyPermanentEffect` are the only control/copy shapes; neither swaps two
  permanents' controllers: Gilded Drake.
- **Repeat-until-condition loop** — no effect keeps going until a predicate
  over what's happened so far is met: Helm of Obedience.
- **Open-ended "as many times as you choose" loop** — every existing loop has
  a fixed or player-capped count: Lim-Dûl's Vault.
- **Fading (RULE 702.32)** — no "enters with N fade counters, remove one each
  upkeep or sacrifice" mechanic: Tangle Wire.
- **Devotion count-selector** — `continuous.count_selector` has no devotion
  entry: Thassa's Oracle.
- **Whole-board phasing** — the phasing mechanism (`GameObject.phased_out`)
  is scoped to a single permanent; nothing phases out every permanent a
  player controls plus the player: Teferi's Protection.
- **Impulsive draw from a non-own / non-library zone** — `ImpulsiveDrawEffect`
  exiles from the caster's own library top only: Ragavan Nimble Pilferer (the
  damaged player's library, plus "spend mana as any color"), Mnemonic
  Betrayal (an opponent's graveyard).
- **Parser recognition of a play/cast-from-top-of-library clause** — the
  engine capability exists (`top_library_permission`, hand-authored) but the
  oracle front-end doesn't recognize the clause: Elsha of the Infinite,
  Bolas's Citadel (also needs a pay-life alternative cost).
- **Standing graveyard-cast permission** — the graveyard-cast family is a
  closed keyword vocabulary (Flashback/Escape), not a card-granted standing
  permission with its own MV filter + once-per-turn tracking (mirroring
  `top_library_permission` for the graveyard zone): Lurrus of the Dream-Den.
- **Extra-turn primitive (RULE 500.7)** — DONE (Batch 18, `GameState.
  extra_turns` FIFO consumed by `GameEngine.begin_turn` + `take_extra_turn`
  effect): an inserted turn is taken right after the current one. **Final
  Fortune** now plays — its "at that turn's end step, you lose the game"
  downside reuses the batch-22 delayed trigger with ``min_turn_offset=1`` so
  it lands on the extra turn's end step, not the casting turn's. Time Warp /
  Last Chance share the primitive (not in this cache).
- **Soulbond (RULE 702.94)** — bare `FLAG` keyword only, no pairing logic:
  Deadeye Navigator.
- **Mutate (RULE 702.140)** — no merge/casting implementation, no
  `EventType.MUTATE`: Lore Drakkis.
- **Bargain additional cost** — bare `FLAG` keyword only, no additional-cost
  handling or "was it bargained" flag: Beseech the Mirror.
- **Sacrifice cause tag / `EventType.SACRIFICE`** — DONE (Batch 15):
  `RulesEngine._move_to_graveyard` fires a distinct `SACRIFICE` occurrence
  (in addition to DIES/LEAVES) for every `put_into_graveyard` sacrifice, so
  "whenever a player sacrifices" is now distinguishable from a plain death.
  Mayhem Devil registered.
- **Grant-protection path** — DONE (Batch 23, `GameObject.temp_protections`
  read by `combat.is_protected_from`, granted via the interactive
  `grant_protection` effect / `RulesEngine.grant_protection_choice`, cleared
  at cleanup). **Mother of Runes** and **Giver of Runes** (its "colorless"
  option supported; "another" restriction a documented drop — no "other
  creature you control" target kind yet) now play.
- **Board-wide ability strip** — DONE (Batch 24, `remove_all_abilities`
  static → `GameObject.loses_all_abilities`, layer 6 RULE 613.7f): strips
  every keyword (`combat._obj_keywords` → empty) and gates triggered/activated
  abilities at fire/activate time. **Humility** now plays (ability strip +
  layer-7b `pt_set` to base 1/1). Dress Down reuses the same static but adds
  an ETB draw + an end-step self-sacrifice and stays deferred; Underworld
  Breach's "escape" grant is a separate gap.
- **Dynamic/count-driven mana amount + cross-graveyard "cards named X"
  selector** — `AddManaEffect` adds a fixed symbol list, and `count_selector`
  has no "cards named X across every graveyard" entry: Rite of Flame.
- **Per-count activation-cost reduction** — `activation_cost_reduction_for`
  supports a flat amount but no per-count formula (mirroring `cost_reduction`'s
  `per` param): Eiganjo Seat of the Empire ("{1} less per legendary creature";
  registered with the Channel ability at full cost, the reduction dropped).
- **Blood Moon's layer-6 ability-removal half** — "Nonbasic lands are
  Mountains" overwrites subtype + grants `{R}` (layer 4) but doesn't strip a
  land's independently-printed mana ability; no pool card needs the
  distinction yet.
- **Inline two-way modal with no bulleted header** — the modal grammar only
  recognizes the bulleted RULE 700.2 block, not a compact "A or B" sentence:
  Pemmin's Aura ("{1}: enchanted creature gets +1/-1 or -1/+1").
- **Conditional search destination** — `SearchLibraryEffect` allows one fixed
  destination per search, not "onto the battlefield tapped if a land, else to
  hand": Archdruid's Charm's first mode.
- **"Put cards from hand onto the battlefield" + Entwine** — every "put onto
  the battlefield" shape moves from a graveyard or library, never an open
  choice from hand; Entwine also has no parser recognition: Tooth and Nail.
- **Assorted bespoke multi-ability cards** each combining several gaps above
  or their own one-off mechanic, left fully unmodeled: Professor Onyx, Jeska
  Thrice Reborn, Tevesh Szat Doom of Fools, Mana Vault (optional-cost /
  state-conditioned upkeep + draw-step triggers), Dauntless Dismantler
  (`{X}{X}{W}`-costed mass-destroy-by-X).
