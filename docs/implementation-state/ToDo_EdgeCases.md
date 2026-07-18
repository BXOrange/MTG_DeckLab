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
- **Phasing (RULE 702.26)** now exists (`GameObject.phased_out`,
  `GameState.permanents`/`permanents_controlled_by` filtering it out,
  `game/effects.py`'s `PhaseOutEffect`), scoped to Robe of Stars' single-
  permanent case — see `Done_Backend.md` "Rules Engine (Phase 2)". Robe of
  Stars' Astral Projection is registered now; Teferi's Protection (a
  whole-board phase-out) isn't in the catalogue yet and would need the
  "phase out together"/multi-permanent family this batch deliberately
  didn't build.
- **Board-count cost reduction for a card still in hand** now exists
  (`continuous.self_cost_reduction_for`, a `per: <count_selector>` param on
  the `"cost_reduction"` `EffectSpec`) — see `Done_Backend.md` "Rules
  Engine (Phase 2)". Embercleave's own "costs {1} less for each attacking
  creature you control" isn't wired up yet (a board-count *during
  declare-attackers specifically*, not a plain controller-scoped selector —
  would need a new `count_selector` entry) but the mechanism it needs
  now exists.
- **{X} cost threading** now exists (`StackItem.x` → `RulesEngine.
  _substitute_x` → a resolving effect's `"x"`-sentinel `amount`/`count`) —
  see `Done_Backend.md` "Rules Engine (Phase 2)". Martial Coup and Nahiri,
  Storm of Stone's `−X` loyalty ability aren't registered yet (not part of
  that batch), but the substitution mechanism they'd need is real now.
- **"Look at top N, take one matching X, put the rest into Y"** now exists
  (`ImpulsiveLookEffect`/`RulesEngine.request_impulsive_look`, Grisly
  Salvage/Commune with the Gods-shaped) — see `Done_Backend.md` "Rules
  Engine (Phase 2)". Nahiri, Heir of the Ancients' −2 and Armored
  Skyhunter's attack trigger aren't registered yet (not part of that
  batch).
- **"Exile and you may play until end of turn" (impulsive draw)** now
  exists (`ImpulsiveDrawEffect`/`RulesEngine.exile_with_play_permission`,
  `GameState.temp_play_permissions`, Light Up the Stage-shaped) — see
  `Done_Backend.md` "Rules Engine (Phase 2)". Sword of Forge and Frontier's
  and Sword of Hearth and Home's own combat-damage triggers stay
  simplified/dropped for now (not part of that batch; see their catalogue
  docstrings for exactly what's kept vs. cut).
- **Hand-zone, non-mana "discard this card: effect" (Channel), and
  Cycling** now exist (`costs.ActivationCost.discard_self`, `RulesEngine.
  discard_specific`) — see `Done_Backend.md` "Rules Engine (Phase 2)".
  Dismantling Wave's Cycling is registered now (its main mode is still
  simplified to a single target, see its catalogue docstring); Eiganjo/
  Sokenzan's Channel abilities aren't registered yet (not part of that
  batch) — the affected lands still work as plain mana sources.
- **"Flash if `<condition>`"/"activate loyalty at instant speed if
  `<condition>`"** now exists (`AbilitySpec.conditional_flash`,
  `game/condition_query.py`, today's whitelist just `entered_this_turn`) —
  see `Done_Backend.md` "Rules Engine (Phase 2)". The Wandering Emperor's
  own "activate loyalty abilities at instant speed" clause is registered
  now; Timely Ward's "cast as though it had flash if it targets a
  commander" isn't (a `"targets_a_commander"` condition key isn't
  whitelisted yet — no card needed it in that batch).
- **A per-firing dynamic reference to "that creature"/"the token this
  effect just created"** is deliberately still not a `TriggeredAbility`
  IR extension — `RulesEngine.check_rampage`/`check_ward`'s bespoke
  "construct a fresh `TriggeredAbility` per firing" pattern is the
  documented, sanctioned answer (`TriggeredAbility`'s own docstring now
  spells this out) for whenever a real card needs it. Kaldra Compleat's
  granted "exile that creature" and Sigarda's Aid's "whenever an Equipment
  you control enters, you may attach *it*" both still hit this wall and
  remain unmodeled — no card has driven building the pattern out for a
  bind-on-load `TriggeredAbility` yet.

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

Real cards from a cEDH cube list, investigated batch-A1 (2026-07-17) while
extending the oracle-text parser. Each stays `UNMODELED` for the stated
reason; not a vague "too hard" — see the cited file for the exact blocker.

- **`Archdruid's Charm`'s third mode needs two independent targeting effects
  in one ability** ("Put a +1/+1 counter on target creature you control. It
  deals damage equal to its power to target creature you don't control.") —
  a real, current engine ceiling (`docs/Reference/
  11_CARD_CATALOGUE_AUTHORING_GUIDE.md` §5's "at most one targeting effect
  per `AbilitySpec`"), compounded by a *dynamic* damage amount ("equal to
  its power", tied to the *other* effect's own target) neither the parser
  nor `game/effects.py` has a shape for. Its first mode also needs a
  conditional search destination ("onto the battlefield tapped if it's a
  land card, otherwise into your hand") — `SearchLibraryEffect` only
  supports one fixed destination per search.
- **`Tooth and Nail`'s second mode ("Put up to two creature cards from your
  hand onto the battlefield.") has no matching engine effect at all** — every
  existing "put onto the battlefield" shape moves a card from a *graveyard*
  or the *top of library*, never an open choice from hand. Its Entwine
  keyword (RULE 700.2's "choose all modes for an extra cost") also has no
  parser recognition yet, but that's the smaller of the two gaps.
- **`Deflecting Swat`'s "You may choose new targets for target spell or
  ability." has no engine mechanism.** Redirecting an *existing* stack
  item's targets (RULE 115.6) needs a target kind spanning both spells and
  abilities on the stack, plus an interactive re-target choice; binding it
  as a no-op would silently do nothing observable for what the card
  actually does, which the fail-closed philosophy treats as worse than
  leaving it unclaimed. `Reiterate`/`Flare of Duplication`'s "you may choose
  new targets for the copy" is the same missing interactive re-target
  primitive, one level removed (copy semantics haven't been built either).
- **`Lavinia, Azorius Renegade`/`Boromir, Warden of the Tower`'s "Whenever an
  opponent casts a spell, if no mana was spent to cast it, counter that
  spell." needs a *reflexive* trigger** — an effect that acts on the exact
  object that fired the triggering event, not a player-chosen target or the
  ability's own source. `RulesEngine.check_ward` needed the identical shape
  for ward's "counter that spell or ability" and had to be built as a fully
  bespoke path outside the generic `AbilitySpec`/`TriggeredAbility` pipeline
  (`game/effects.py`'s `WardEffect` docstring) — no generic version of that
  exists yet. The underlying condition data *is* tracked already
  (`EventType.SPELL_CAST`'s `free` flag, set by `RulesEngine.
  cast_without_paying` — reused for item 2's alternative-cost family this
  same batch), only the reflexive-target wiring is missing. Both example
  cards also carry a second, independently-unmodeled clause regardless
  (Lavinia's cost-prohibition static; Boromir's "the Ring tempts you"), so
  neither reaches `MODELED` even once this is built.
- **`Summoner's Pact`/`Pact of Negation`'s "At the beginning of your next
  upkeep, pay `<cost>`. If you don't, you lose the game." needs a
  *dynamically-created* delayed trigger** (RULE 603.7) — every triggered
  ability today is bound once at `GameObject` creation (bind-on-load) and
  reused for the object's whole lifetime; nothing creates a new, one-shot
  trigger tied to a *specific future event* ("your next upkeep, and only
  that one") at resolution time. Also needs an interactive "pay or lose"
  choice, a new primitive on top.
- **`Kinnan, Bonder Prodigy`'s mana-doubling trigger has no event to key
  off.** "Whenever you tap a nonland permanent for mana" would need a
  distinguishable per-tap mana-production event; `GameEngine.tap_for_mana`
  doesn't fire one today (mana is added straight to the pool). Its `{5}{G}
  {U}` ability ("look at the top five cards... put a non-Human creature card
  from among them onto the battlefield, the rest to the bottom in random
  order") is a related but different shape from the generic library-search
  family (`SearchLibraryEffect` searches the *whole* library toward one
  fixed destination, not "look at exactly N, place the rest on the bottom
  in a fresh random order").
- **`Pemmin's Aura`'s "{1}: Enchanted creature gets +1/-1 or -1/+1 until end
  of turn." is an inline two-way modal choice with no bulleted "Choose
  one —" header** — the modal grammar (`parser/oracle/catalogue/modal.py`)
  only recognizes the bulleted RULE 700.2 block shape; this compact
  same-sentence "A or B" form is a different, unhandled template. (Its other
  three activated abilities — tap/untap/gain flying/gain shroud on enchanted
  creature — are modeled; only this fourth line blocks the card.)
- **`Dress Down`'s "Creatures lose all abilities." and `Underworld Breach`'s
  "Each nonland card in your graveyard has escape..." are both standing
  static-ability clauses** outside this batch's scope
  (`parser/oracle/catalogue/static_handlers.py`, owned by a separate wave).
  Both cards' *other* clauses — the standing end-step self-sacrifice
  trigger — are modeled this batch (`parser/oracle/segmenter.py`'s
  `_PHASE_TRIGGER_RE`, `game/effects.py`'s `SacrificeSelfEffect`).
- **`Teferi's Protection`'s phasing clause is still unregistered** — a
  phasing *mechanism* now exists (`GameObject.phased_out`, see the entry
  above), but only scoped to Robe of Stars' single-permanent case; Teferi's
  Protection needs the "phase out every permanent you control, plus
  yourself" whole-board family, which this batch deliberately didn't
  build. Its trailing "Exile ~." *is* modeled this batch (`ExileEffect`'s
  `target_kind=None` self mode), so the card is blocked purely by the
  missing whole-board phasing variant.
- **`Ragavan, Nimble Pilferer`/`Mnemonic Betrayal`'s exile-and-grant-
  temporary-cast-permission effect ("impulsive draw") is still
  unregistered** — the generic mechanism now exists (see the entry above,
  `ImpulsiveDrawEffect`/`RulesEngine.exile_with_play_permission`), but both
  cards combine it with clauses the mechanism doesn't cover on its own:
  Ragavan exiles from *the damaged player's* library (not its own
  controller's) and grants "spend mana as though it were mana of any
  color" alongside the temporary cast permission; Mnemonic Betrayal's
  exile-from-graveyard-and-cast is a different zone than the mechanism's
  library-top source. Neither is registered yet.
- **`Elsha of the Infinite`/`Bolas's Citadel`'s actual play/cast-from-top-of-
  library permission clause has no parser-front-end recognition** (only
  hand-authored per-card today) — see `backend/ToDo_Backend.md` "Rules
  Engine (Phase 2)" for the full writeup. Their "You may look at the top
  card of your library any time." sibling clause *is* now claimed (a
  documented no-op, `parser/oracle/segmenter.py`'s
  `_LOOK_AT_TOP_ANY_TIME_RE`), so it no longer blocks a card on its own.
- **`Professor Onyx`'s `+1`/`−3`/`−8` loyalty abilities are each their own
  unmodeled mechanic** (a "look at top 3, one to hand + rest to graveyard"
  choice; "sacrifice a creature with the greatest power" selector; a
  6-times-repeated conditional discard-or-lose-life loop) — unrelated to,
  and independent of, its Magecraft line (which *is* modeled this batch,
  along with a general Magecraft trigger-family handler,
  `parser/oracle/segmenter.py`'s `_MAGECRAFT_RE` — `Witherbloom Apprentice`,
  which has no other abilities, reaches `MODELED` from it). Magecraft's own
  "or copy" firing condition (as opposed to "cast") is also unreachable
  today since nothing in the engine can produce a spell copy in the first
  place — see the `Reiterate`/`Flare of Duplication` entry above.

Batch A2 (2026-07-17), extending `static_handlers.py`/`continuous.py` with
six new reusable static-clause families (activated-ability prohibition,
type-filtered spell-cost tax, per-turn cast-count cap, self "doesn't untap",
global ETB-trigger suppression, opponent-scoped board-wide "enter tapped")
plus a RULE 613.5 layer-4 subtype-overwrite family and the RULE 903.3
"can be your commander." no-op claim:

- **`Mana Vault`'s "At the beginning of your upkeep, you may pay {4}. If you
  do, untap this artifact." and "At the beginning of your draw step, if
  this artifact is tapped, it deals 1 damage to you." are each their own
  unmodeled conditional trigger** — an optional-cost upkeep trigger and a
  state-conditioned ("if this artifact is tapped") draw-step trigger,
  neither a shape the generic trigger-clause handlers cover yet. Its "This
  artifact doesn't untap during your untap step." sibling line *is* modeled
  this batch (`static_handlers._NO_UNTAP_RE`, `continuous.
  has_no_untap_static`) — Basalt Monolith/Grim Monolith, which have no
  other unmodeled lines, reach `MODELED` from it.
- **`Dauntless Dismantler`'s "{X}{X}{W}, Sacrifice this creature: Destroy
  each artifact with mana value X." is an unmodeled mass-destroy-by-X
  activated ability** — the generic "destroy each X" one-shot family
  (`handlers.py`) doesn't yet accept an `{X}{X}{W}`-costed activation
  wrapper with the ability's own announced X flowing into the filter
  (`mana value X`). Its "Artifacts your opponents control enter tapped."
  sibling line *is* modeled this batch (`static_handlers.
  _OPPONENTS_ENTER_TAPPED_RE`, `continuous.enters_tapped_from_static`) —
  Manglehorn, which has no other unmodeled lines (its ETB destroy-artifact
  trigger was already covered), reaches `MODELED` from it.
- **`Jeska, Thrice Reborn`'s "~ enters with a loyalty counter on her for
  each time you've cast a commander from the command zone this game."
  (a game-history-counted variable starting loyalty), "0: Choose target
  creature. Until your next turn, if that creature would deal combat
  damage to one of your opponents, it deals triple that damage to that
  player instead." (a delayed, conditional damage-replacement effect tied
  to a chosen target), and `Tevesh Szat, Doom of Fools`'s "+1: You may
  sacrifice another creature or planeswalker. If you do, draw two cards,
  then draw another card if the sacrificed permanent was a commander."
  (a conditional draw-amount keyed to the sacrificed object's own
  commander-ness) and "−10: Gain control of all commanders. Put all
  commanders from the command zone onto the battlefield under your
  control." (mass commander reanimation + control-change) are each
  independently unmodeled, unrelated to this batch's scope** — genuinely
  complex bespoke mechanics, not a static/continuous-effect shape. Both
  cards' own "~ can be your commander." line *is* now claimed (a
  documented no-op, `static_handlers.commander_eligibility_line`, wired
  into `gate._process_line`) and no longer appears in either card's
  `unclaimed` list, but neither reaches `MODELED` overall because of the
  clauses above.
- **`Blood Moon`/`Magus of the Moon`'s "Nonbasic lands are Mountains." only
  overwrites the affected land's subtype and grants it a red mana ability
  (RULE 613.5's layer-4 half) — it does not strip the land's own *printed*
  mana ability** (`type_change`'s new `set_subtypes` param +
  `grant_mana_ability`, `game_object._derived_subtypes`,
  `continuous._has_subtype`). A real dual land with an explicit "{T}: Add
  {U} or {B}." text keeps producing its original colours *in addition to*
  the newly granted {R} — the layer-6 ability-removal half of Blood Moon's
  real-world function (which, per official rulings, only actually shuts off
  a land whose colour production is inherent to a basic land type it no
  longer has, not a land with independently-printed mana text) isn't
  modeled. No card in the pool needs the removal half distinguished from
  the addition half yet, so this is a known, deliberate scope limit rather
  than a bug.

Batch B1 (2026-07-17), hand-authored `ability_catalogue.py` entries (18 of
30 assigned cards reached `MODELED`/registered — 6 via generic parser/engine
extensions: Walking Ballista's self-reference vocabulary, Village
Bell-Ringer's mass-untap selector, Root Maze/Blind Obedience's enters-tapped
family, Abrupt Decay's target-offer-time mana-value cap, Arbor Elf's new
"forest" target kind; 12 via direct catalogue registration, several
deliberately partial). The remaining 12 stay unclaimed/unregistered:

- **`Mana Drain`'s "At the beginning of your next main phase, add an amount
  of {C} equal to that spell's mana value." and `Corpse Dance`'s "Exile it
  at the beginning of the next end step." both need a dynamically-created,
  one-shot delayed trigger tied to a specific future event** (RULE 603.7) —
  the same missing primitive `Summoner's Pact`/`Pact of Negation` hit above;
  every triggered ability today is bound once at `GameObject` creation and
  reused for the object's whole lifetime, nothing creates a fresh trigger
  tied to one specific upcoming step. Both cards are registered anyway with
  just their modelable half (Mana Drain's counter; Corpse Dance's return-top-
  creature-with-haste, `ReturnTopGraveyardCreatureWithHasteEffect`), the
  delayed tail dropped per the Sword of Forge and Frontier precedent.
- **`Combat Celebrant`'s exert ("you may exert it as it attacks") and
  "after this phase, there is an additional combat phase." are both
  unmodeled mechanics with no engine primitive at all** — exert isn't a
  one-shot/triggered/static effect shape, it's an optional choice offered
  as part of *declaring an attacker* (RULE 508.1g), and an extra combat
  phase needs the turn-structure step-sequencer to re-run the whole combat
  phase, neither of which this engine's `AbilitySpec`/`GameEffect` pipeline
  can express yet.
- **`Wild Growth`'s "Whenever enchanted land is tapped for mana, its
  controller adds an additional {G}." and `Price of Glory`'s "Whenever a
  player taps a land for mana, if it's not that player's turn, destroy
  that land." both need a distinguishable per-tap mana-production event**
  — `GameEngine.tap_for_mana` doesn't fire one today (mana goes straight to
  the pool), the same gap `Kinnan, Bonder Prodigy`'s entry above already
  documents. Price of Glory additionally needs a *reflexive* trigger
  ("destroy **that land**", the exact object that fired the triggering
  event, not a chosen target) — the same bespoke-primitive gap `Lavinia,
  Azorius Renegade`'s entry above documents; `Mana Web`'s "tap all lands
  that player controls that could produce any type of mana that land could
  produce" compounds the same missing mana-tap event with a mana-type-
  matching mass-tap effect that also doesn't exist.
- **`Dualcaster Mage`'s "copy target instant or sorcery spell" has no
  engine mechanism** — nothing in this engine can produce a spell copy in
  the first place, the same gap the `Reiterate`/`Flare of Duplication`
  entry above documents (Wandering Archaic, elsewhere in the cube, needs
  the identical shape).
- **`Helm of Obedience`'s "mills a card, then repeats this process until a
  creature card or X cards have been put into their graveyard, whichever
  comes first" is an unmodeled repeat-until-condition loop** — every
  existing mill effect mills a fixed count, none has a "keep going until a
  predicate over what's been milled so far is met" shape.
- **`Eldritch Evolution`'s "Search your library for a creature card with
  mana value X or less, where X is 2 plus the sacrificed creature's mana
  value." needs a second dynamic-value source beyond {X} cost threading**
  — `StackItem.x`/`RulesEngine._substitute_x` only threads a spell's own
  *announced* {X}; nothing stashes an additional cost's sacrificed
  permanent (or its mana value) anywhere a resolving effect can read it
  back (contrast Sunforger's `unattach_self`, which does get such a stamp,
  `GameObject.last_unattached_from_id` — sacrifice has no equivalent).
- **`Tangle Wire`'s Fading is not modeled at all** — no "enters with N fade
  counters, remove one each upkeep or sacrifice" mechanic exists (RULE
  702.32), a bigger gap than its own "tap N permanents per fade counter"
  upkeep trigger, which would otherwise be a plausible one-off effect.
- **`Thassa's Oracle`'s "your devotion to blue" has no count-selector
  source** — `continuous.count_selector`'s vocabulary has no devotion
  entry; per this session's ground rules, not faked with a wrong count
  source (creature count, mana value, etc. would all be incorrect).
- **`Fire Covenant`'s "deals X damage divided as you choose among any
  number of target creatures" has no divided-damage primitive** —
  `DealDamageEffect`'s existing `count` > 1 shape applies the *full*
  amount to *every* chosen target (Volcanic Salvo-shaped), not a shared
  pool split across them; the `pay X life` additional cost side is
  otherwise trivial (`additional_cost`'s existing `pay_life: "x"` idiom).
- **`Hope of Ghirapur`'s "target player who was dealt combat damage by ~
  this turn" is a per-firing dynamic reference this engine has no generic
  primitive for** — the same `RulesEngine.check_rampage`/`check_ward`
  bespoke-per-firing-construction pattern (`TriggeredAbility`'s own
  docstring) would be needed, and no card in this cube's earlier batches
  has driven building a reusable version of it yet.
- **`Umbral Mantle`'s "Equipped creature has '{3}, {Q}: This creature gets
  +2/+2 until end of turn.'" needs a layer-6 grant of an *activated*
  ability** — only `grant_triggered_ability`/`grant_mana_ability`/
  `grant_keyword` exist; nothing synthesizes a cost-bearing `ActivatedAbility`
  onto another permanent the way those synthesize a `TriggeredAbility`/mana
  option/keyword. A hollow registration (Equip {0} alone, already covered
  by the keyword catalogue regardless) would deliver none of the card's
  actual function, so it's left unregistered rather than forced.
- **`Eiganjo, Seat of the Empire`'s "This ability costs {1} less to
  activate for each legendary creature you control." still has no matching
  primitive** — batch B2 (below) built `continuous.
  activation_cost_reduction_for`/`GameEngine._reduced_activation_mana` for
  Power Artifact's flat "{2} less" activation-cost reduction, but Eiganjo
  needs a *per-count* formula ("{1} less for each legendary creature you
  control", mirroring `cost_reduction`'s spell-cost `per` param) that
  primitive doesn't support yet; the card is still registered with the
  Channel ability at its full, undiscounted cost, the reduction dropped per
  the Sword of Forge and Frontier precedent. Extending `activation_cost_
  reduction_for` with a `per`/count-selector param would close this cheaply
  now that the flat-amount half exists.

Batch B2 (2026-07-17), hand-authored `ability_catalogue.py` entries (12 of
30 assigned cards reached `MODELED`/registered — 2 deliberately partial,
Damn/Ephemerate — plus several new reusable primitives along the way:
activation-cost reduction, `effect_binder`'s "not_you" group-trigger scope
and a `LAND_PLAYED`/`UNTAP` `_GROUP_CONTROLLER_EVENT_KEYS` mapping, a new
`blink` primitive, `put_hand_cards_on_top`, and a shared `wheel` "each
player shuffles hand+graveyard, draws seven" effect. Also fixed two
previously-latent bugs surfaced by actually exercising a triggered ability
that targets a spell still on the stack, which nothing in the suite had
done before: `GameEngine.resolve_until_stable` fell through and resolved
the stack's top item even when `put_triggers_on_stack` had just opened a
`pending_choice` for the trigger's own target/mode/"you may" choice (a
still-unresolved spell would silently resolve for real while the player
was nominally still choosing whether/what to counter it with); and
`RulesEngine._resolve_choice_option` only ever searched `state.
permanents()` for a `trigger_target` choice's `instance_id`, so a
``kind="spell"`` target (an object sitting on the stack, not the
battlefield) could never actually resolve — both fixed by Nether Void's
"whenever a player casts a spell, counter it unless…" test, which is
exactly this shape.) The remaining 18 stay unclaimed/unregistered:

- **`Neoform`'s "Search your library for a creature card with mana value
  equal to 1 plus the sacrificed creature's mana value" is the same
  `Eldritch Evolution` gap already logged above** — nothing stashes an
  additional cost's sacrificed permanent (or its mana value) anywhere a
  resolving effect can read it back; confirmed the same blocker rather than
  re-investigated from scratch.
- **`Demonic Consultation`'s "Choose a card name." has no matching input
  primitive** — every existing choice (search, modal, trigger-target) offers
  a list of *already-visible* options; nothing lets a player name an
  arbitrary card *before* any zone is examined, which is what RULE 601.2c
  naming requires here (as opposed to `SearchLibraryEffect`'s "look and
  then pick" shape, which would show information the real card doesn't
  reveal). `Possibility Storm` needs the same missing "exile from the top
  until a card matches a filter, non-matches to the bottom in random order"
  loop shape as this card's own reveal-until-named-card half, *plus* a
  much bigger architectural change — intercepting *every* player's *every*
  spell cast from hand, not a single card's own trigger — so it's logged
  separately below rather than treated as "just" the same gap.
- **`Lim-Dûl's Vault`'s "As many times as you choose, you may pay 1 life…"
  is an unmodeled open-ended repeat-as-many-times-as-you-choose loop** — no
  effect in `game/effects.py` re-offers the same choice an unbounded number
  of times gated only by "may pay 1 life again"; every existing loop
  (search "up to N", modal "choose N or more") has a fixed or player-capped
  count, not an open-ended one.
- **`Tibalt's Trickery`'s "Choose 1, 2, or 3 at random." needs a
  random-number primitive that doesn't exist anywhere in this engine** —
  confirmed via a repo-wide search: no `random.choice`/`randint`/`randrange`
  call appears in `game/*.py` or `models/*.py` (library shuffling is the
  only randomness in the whole engine, and it doesn't produce a usable
  number). Its own "exile from the top until a nonland card with a
  different name" clause also needs the same missing dig-until-match loop
  `Demonic Consultation`'s entry above documents.
- **`Gilded Drake`'s "exchange control of this creature and up to one
  target creature an opponent controls" has no control-*exchange*
  primitive** — `game/effects.py`'s `control_change` static (`StaticAbility`
  layer 2, Mind Control-shaped) and `CopyPermanentEffect` are the only
  control/copy-adjacent shapes that exist, and neither is a mutual swap of
  two permanents' controllers; the "sacrifice if you don't/can't exchange"
  and "still resolves if its target becomes illegal" riders compound it
  further.
- **`Squirrel Nest`'s "Enchanted land has '{T}: Create a 1/1 green Squirrel
  creature token.'" is the same `Umbral Mantle` gap already logged above**
  — no layer-6 grant-of-an-*activated*-ability primitive exists yet (only
  `grant_triggered_ability`/`grant_mana_ability`/`grant_keyword` do);
  confirmed the same blocker rather than re-investigated from scratch.
- **`Shatterskull Smashing`'s "deals X damage divided as you choose among up
  to two target creatures and/or planeswalkers" is the same `Fire Covenant`
  divided-damage gap already logged above** — `DealDamageEffect`'s `count`
  > 1 shape still applies the *full* amount to every chosen target, not a
  shared pool split across them; confirmed still true rather than
  re-investigated from scratch.
- **`Power Artifact` reached `MODELED`** via a new activation-cost-reduction
  primitive (`continuous.activation_cost_reduction_for`) — see the batch
  summary above; not a gap, listed here only so a future reader doesn't
  wonder why it's absent from this skip list.
- **`Lurrus of the Dream-Den`'s "Once during each of your turns, you may
  cast a permanent spell with mana value 2 or less from your graveyard."
  needs a new standing graveyard-cast-permission mechanism** — the existing
  graveyard-cast family (`GameEngine._graveyard_cast_keyword`/
  `_castable_from_graveyard`) is a closed vocabulary keyed to a printed
  keyword (Flashback/Escape), not a card-granted standing permission with
  its own MV filter — unlike `top_library_permission`'s architecture (which
  this would need to mirror: a marker effect + a `can_cast`-consulted
  helper), nothing analogous exists for the graveyard zone, and it would
  also need its own once-per-turn use-tracking distinct from
  `ActivatedAbility.once_per_turn` (this isn't an activated ability at
  all). A good blueprint for a focused future wave, not attempted here
  given the size of this one.
- **`Cloudstone Curio`'s "return another permanent you control that shares
  a permanent type with it" is a per-firing dynamic reference this engine
  has no generic primitive for** — the same `Hope of Ghirapur`-shaped gap
  already logged above (`RulesEngine.check_rampage`/`check_ward`'s bespoke-
  per-firing-construction pattern would be needed): the bounce target has
  to be compared against whatever object *just entered* to fire the
  trigger, not a fixed `target_kind` filter `ReturnToHandEffect` can express.
- **`Seedborn Muse` reached `MODELED`** via a new `effect_binder._group_ok`
  ``"not_you"`` controller scope + a `TapEffect` `"permanents_you_control"`
  selector — see the batch summary above; not a gap, listed here only so a
  future reader doesn't wonder why it's absent from this skip list.
- **`Final Fortune`'s "Take an extra turn after this one." has no matching
  primitive at all** — confirmed via a repo-wide search: no "extra turn"/
  "additional turn" concept exists anywhere in `game/phases.py`/
  `game_engine.py` (turn order is a fixed round-robin,
  `GameState.next_active_index`). RULE 500.7's whole extra-turn family
  (Time Warp, Karn's Temporal Sundering, Nexus of Fate, …) is blocked on
  this same absolute gap, not just this card's own "lose the game at that
  turn's end step" rider.
- **`Deadeye Navigator`'s Soulbond has zero engine behavior** — confirmed
  via a repo-wide search: `Soulbond` appears only as a bare `FLAG` keyword
  in `parser/oracle/catalogue/keywords.py`, with no pairing/unpairing logic
  anywhere in `game/`. No other Soulbond card in this pool is modeled
  either, so this is a whole-mechanic gap, not specific to this card's own
  "exile then return" granted ability (which would also need a new
  activated-ability-*grant* primitive, the same `Umbral Mantle`/`Squirrel
  Nest` gap, on top of Soulbond itself).
- **`Nether Void` reached `MODELED`** via a straightforward reuse of the
  existing `counter`/`unless_pays` effect and an unscoped "group" trigger
  subject (already matches any player, not just "you") — see the batch
  summary above for the two latent bugs its test surfaced; not a gap,
  listed here only so a future reader doesn't wonder why it's absent from
  this skip list.
- **`Beseech the Mirror`'s Bargain has zero engine support** — confirmed via
  a repo-wide search: `Bargain` appears only as a bare `FLAG` keyword in
  `parser/oracle/catalogue/keywords.py`, with no additional-cost handling
  (unlike Kicker/Buyback/Escape, which each have a real `costs.py`/
  `AbilitySpec` shape) and no "was this spell's additional cost paid" flag
  analogous to `kicker_count` for the "if bargained, you may cast the
  exiled card free if its mana value is 4 or less" conditional half to key
  off of, even setting aside the compound "then put it into your hand if it
  wasn't cast this way" destination logic.
- **`Mayhem Devil`'s "Whenever a player sacrifices a permanent" needs a
  cause tag this engine's death/graveyard events don't carry** —
  `RulesEngine._move_to_graveyard` fires the same `LEAVES_BATTLEFIELD`/
  `DIES` pair regardless of *why* a permanent left (destroyed, sacrificed,
  or a specific effect-driven sacrifice, RULE 701.17) — there's no
  `EventType.SACRIFICE` and no "cause" field on the fired event a trigger
  condition could filter on, so a "whenever a player sacrifices" trigger
  can't be distinguished from "whenever a permanent dies" without a real
  (and fairly invasive, since every `sacrifice`/`put_into_graveyard` call
  site would need to thread a cause through) engine change.
- **`Lore Drakkis`'s "Whenever this creature mutates" needs a trigger event
  Mutate itself doesn't fire** — confirmed Mutate (RULE 702.140) has no
  actual casting-mechanic implementation in this engine (no "cast it by
  putting it over/under target non-Human creature" merge logic, no
  `EventType.MUTATE`), only a bare `FLAG` keyword recognition in
  `parser/oracle/catalogue/keywords.py`; the trigger this card needs can't
  exist before the mechanic it fires off of does.
- **`Giver of Runes`'s "gains protection from colorless or from the color of
  your choice" can't be granted by any effect** — confirmed
  `combat.is_protected_from` reads only `obj.effective_oracle_text`
  (printed text, plus a layer-3 word-substitution `text_change` static) —
  unlike every other keyword (`combat._obj_keywords`, unioning printed +
  intrinsic + layer-6-granted + temp-until-eot sources), protection has no
  granted-keyword-set path at all, so neither a layer-6 `grant_keyword` nor
  `PumpEffect`'s `keywords` list actually confers real protection even
  though nothing stops a spec from naming "protection from X" in one. A
  real gap affecting *any* future "grants protection" card (Mother of
  Runes and siblings), not just this one — worth a dedicated primitive
  before hand-authoring another one of these.
- **`Humility`'s "All creatures lose all abilities" is a board-wide
  ability-*strip*, which this engine's layer-6 removal only does per
  named keyword** — `remove_keyword` (RULE 613.7f) subtracts specific,
  listed keywords from `_obj_keywords`; it has no "remove everything"
  mode, and even a maximal keyword list wouldn't touch a creature's
  triggered/activated/static abilities (`obj.triggered_abilities`/
  `activated_abilities`/`static_effects`), which the layer system's
  keyword-removal path was never wired to at all. The "base power and
  toughness 1/1" half is trivially expressible (`pt_set`), but a partial
  model dropping the ability-strip half would misrepresent the card's
  entire point (making creatures with removal-relevant triggered/activated
  abilities keep them), so the whole card stays unclaimed.
- **`Rite of Flame`'s "add {R} for each card named Rite of Flame in each
  graveyard" needs two independent gaps closed** — `AddManaEffect` only
  ever adds a fixed list of colour symbols (no dynamic/count-driven amount
  shape at all, unlike `DrawCardEffect.count_selector`), and
  `continuous.count_selector`'s vocabulary has no "cards named X" entry, let
  alone one scanning *every* player's graveyard rather than just the
  controller's own (`count_selector`'s existing "cards_in_your_graveyard"
  is controller-scoped only). Both would need building for this one card;
  neither is attempted here.
