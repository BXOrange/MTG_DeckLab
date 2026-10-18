# Engine mechanic notes

Reusable engine mechanisms and their invariants. Card-specific behaviour lives in
the card's implementation and tests; shipped narrative in
`docs/implementation-state/Done_Backend.md` (search the mechanic's name there).

## Identity and snapshots

- Objects keep a stable `instance_id` plus a monotonic `zone_incarnation` that
  identifies one zone stay (RULE 400.7). Remembered/linked references (exile until
  departure, delayed graveyard returns, cast-cost IDs, event snapshots) compare
  incarnations, so leaving and re-entering a zone breaks the link.
  `zone_visit_counters` preserves counter LKI for departed source visits;
  resolving amounts and conditions use it only after that source visit ends.
  Live source identity remains unchanged for selectors such as "other".
- Aura/Equipment trigger predicates resolve their source by instance ID from the
  *current* state. Snapshot callbacks retain Python closures, so a captured
  `GameObject` can hold pre-rollback data after an action error or take-back
  (`tests/test_ophidian_eye_trigger.py`).
- Exile until departure (RULE 610.3): `ExileEffect.until_source_leaves` with
  state-owned source/exile links; a battlefield removal emits a separate
  notification whose batch returns linked cards at once, without a leaves
  trigger. Ordinary two-ability linked exile stays on the separate-trigger path.
- Linked pools record successful exile visits through `GameState.track_exiled_with`,
  including activation costs, library searches and multi-pick choices. Token
  transfers copy these exact visits; returns never reconstruct them from IDs.
  Ability sources retain their pre-cost incarnation. Crew and saddle attack
  events freeze participant visits; later zone changes break membership.
- Timed copies use ordered `copy_mechanics` snapshot layers. Cleanup and
  next-end-step expiration remove only the matching layers, preserving newer
  permanent copies and independent durations. Zone changes discard the layers;
  cloning retains them. End-step durations expire before beginning-of-step
  trigger checks, independently of delayed returns on the stack.
- Exile/return sequences compose through `effects/exile_sequences.py`'s
  `blink`: source/target/event-visit selection, frozen departing-copy recipients,
  `exile_effects`, return timing and entry options, then `return_effects`.
  `bind` captures pre-exile measurements; a bind in the return body measures
  the new permanent after its entry choices. `return_if_successful` gates
  that body on actual return. All suspension uses the existing resolution
  and entry frames; phase bodies must not introduce unannounced targets.
  Control branches use `if_else` before exile. A referent body with
  `referent="target", acting="controller"` freezes that subject’s controller
  before any body instruction; continuation frames retain it through choices.
  Conditional returned-type riders inspect the new face after entry choices.
  Printed card-type filters and return control are independent linked-pool axes.
  `return_to_battlefield=False` runs only the successful exile phase;
  its body can install a `create_turn_trigger` with `grant_zone="exile"`.
  The shared persistent watcher binds the owner and exact zone visit,
  rechecking that visit at resolution. Optional branches and `bind` express
  measured return choices; source returns use the same entry batch as blink.
  Standing exile-play permissions retain the exile visit and filter the
  selected card face, including MDFC land faces.
- Saga completion checks chapter abilities waiting for stack placement as
  well as those already on the stack (RULE 704.5s / 714.4). An unrelated
  trigger or a chapter from an older source visit does not protect a Saga.

## Resolution

- Aggregate target limits share power and mana-value axes across casting,
  activation, trigger choices, copied targets and board metadata. Any-number
  trigger groups use their legal pool, with no fixed target cap. Partial
  trigger announcements live in GameState for clone/undo. Multiple targeted
  graveyard returns reuse exact simultaneous entry batches; each entry
  choice finishes before later instructions, including source flicker.

- Deferred source flicker delays the whole shared blink, independently of
  its later return timing and entry data. Delayed self captures retain the
  original resolving visit, including when the source left before arming.
  Crew uses an incarnation-scoped self grant; its animation cannot survive
  exile or animate the returned back face.

- Saga flavor labels are normalized independently of chapter bodies. An
  omitted return recipient means the instructed player (RULE 110.2a);
  explicit owner/your-control clauses remain separate. Source-pronoun
  flickers use the trigger’s established self scope and exact blink visit.
  Coordinated player verbs retain an explicit group subject until another
  subject is stated, so opponent sacrifice/life-loss pairs affect opponents.

- Untargeted control changes reuse structured battlefield groups, independent
  duration, untap and haste parameters. Group selection uses the resolving
  ability controller even after its source changes controller. Untargeted
  land choices distinguish unrestricted pools from lands you control.

- Loss replacements use `PLAYER_WOULD_LOSE`; `PLAYER_LOST` announces only an
  actual loss. State-owned APNAP loss batches defer game-over checks until all
  choices and recovery instructions finish. Replacement descriptors preserve
  current-state references across rewind, including nested life-gain choices.
- Graveyard shuffling uses ordinary zone exits and a state-owned finalizer to
  group all exits across Commander decisions. The finalizer releases only its
  own held event batch; concession cancels that player's recovery without
  discarding other players' decisions or an outer spell's instructions.
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

- Outside-game cards (RULE 400.11) live in `Player.sideboard`, outside all
  zones and generic object/target pools. A live `sideboard_cast_permission`
  admits owned nonland cards through ordinary casting; successful commitment
  removes outside membership and preserves the instance ID. Sideboard views
  remain owner-private even when hands are revealed or another player controls
  the turn (RULE 723.4/5); turn controllers receive uniform opaque selections
  and generic rejected-announcement errors.
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
