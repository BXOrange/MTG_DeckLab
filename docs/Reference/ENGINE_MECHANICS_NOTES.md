# Engine mechanic notes

Reusable engine mechanisms and their invariants. Card-specific behaviour lives in
the card's implementation and tests; shipped narrative in
`docs/implementation-state/Done_Backend.md` (search the mechanic's name there).

## Identity and snapshots

- Objects keep a stable `instance_id` plus a monotonic `zone_incarnation` that
  identifies one zone stay (RULE 400.7). Remembered/linked references (exile until
  departure, delayed graveyard returns, cast-cost IDs, event snapshots) compare
  incarnations, so leaving and re-entering a zone breaks the link.
- Aura/Equipment trigger predicates resolve their source by instance ID from the
  *current* state. Snapshot callbacks retain Python closures, so a captured
  `GameObject` can hold pre-rollback data after an action error or take-back
  (`tests/test_ophidian_eye_trigger.py`).
- Exile until departure (RULE 610.3): `ExileEffect.until_source_leaves` with
  state-owned source/exile links; a battlefield removal emits a separate
  notification whose batch returns linked cards at once, without a leaves
  trigger. Ordinary two-ability linked exile stays on the separate-trigger path.

## Resolution

- Placement riders travel in `placed_effects` and run only after a successful
  choice, with the placed object as their referent. Unrestricted attacking
  placement offers every legal defender; an explicit defending-player placement
  restricts the choice to that player and their planeswalkers (RULE 508.4).
- `DelayedTrigger.step_player_id` can anchor a future step to an owner while
  retaining the original ability controller. Grants cache both host and grantor
  zone incarnations, so a returned permanent receives fresh granted effects.
- RULE 603.8 state triggers use an internal `STATE_CHECK` after the SBA sweep,
  not a fabricated zone-change event. Collection suppresses another firing
  while the same source/incarnation/ability has one pending or on the stack.
  Controller-relative state gates read the current host controller.
- Void's game-wide condition reads nonland departure snapshots and
  `SPELL_CAST.warped`. The Warp casting path that emits the latter is tracked
  separately in MEC-119; ordinary casts never satisfy that branch.

- Continuous characteristics are recomputed between resolving instructions, but
  state-based actions never run inside a resolution (RULE 613/704).
- Resolution casts (RULE 608.2g/707.12): library, graveyard and exile offers use
  the shared resolution-play choices and preserve alternative costs, targets and
  X; uncast copies cease before priority returns.
- Copy targets (RULE 707.10c) use `GameState` target rounds before a batch of
  copies enters the stack; copies keep effects, X, source/event references and
  target incarnations. Untargeted event copies keep state-owned stack recipes when
  the original leaves. Spell-copy prohibitions are static markers checked before
  creation. Aura/Bestow/Mutate targets and session rewind reuse this mechanism.
- Suspended choices preserve graveyard incarnations, player referents and the
  resolving spell through the last interactive instruction.

## Costs and choices

- Mana effects attached to individual produced units (RULE 106.6) travel through
  `ManaPool.rider_lots` and `last_payment_riders`; partial payments consume only
  their own units. Next-cast delayed triggers are state-owned and independent of
  spending the generated mana. Immediate spending effects precede `SPELL_CAST`.
- `_apply_entry_counters` combines printed, granted and mana-derived entry counters
  before one replacement-aware placement per kind (RULE 122.6 / 614.12). Callers
  must not also apply granted entry counters separately.
- Announced costs (RULE 601.2i) expose their pools on the legal action
  (`return_cost`, `exile_cost`, `ActivationCost.sacrifice_count`); the shared
  board gathers targets first, then the cost picker, and submits the choice IDs,
  which are validated before payment. `CAST_COST_PAID` fires after all costs.
- Target groups with a bound use `TargetSpec.any_number` / `total_power_max`;
  casting, copy changes and resolution check the whole group.
- Counter placement prohibitions use ordinary static groups and also guard entry
  counters (RULE 614.12); a prohibited move leaves source counters intact
  (RULE 122.5).
- Miracle: a private first-draw reveal creates a real linked trigger whose
  resolution alone opens the hand-cast dialog; a different hand incarnation or a
  countered trigger closes the permission.
- Cleanup discards (RULE 514.1) use the shared pending-choice card picker before
  damage and temporary effects are cleared; other seats see `waiting_on_choice`
  as a non-blocking popup.
- Multiplayer trigger-placement choices leave the announced ability on the stack
  for responses instead of auto-resolving it.
