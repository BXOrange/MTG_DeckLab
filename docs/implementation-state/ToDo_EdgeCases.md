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
