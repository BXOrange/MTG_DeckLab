# Engine mechanic notes

Reusable engine mechanisms and their invariants. Card-specific behaviour lives in
the card's implementation and tests; shipped narrative in
`docs/implementation-state/Done_Backend.md` (search the mechanic's name there).

## Rules subsystem navigation

`game/rules/misc_mixin.py` composes focused mixins while retaining the
`MiscSystemsMixin` import used by `RulesEngine`. Its inherited operations live in:

| Responsibility | Module under `game/rules/` |
| --- | --- |
| Optional energy/life/cost payments and collective payment choices | `payment_choices_mixin.py` |
| Player-cost validation and payment | `player_costs_mixin.py` |
| Player/object votes and outcomes | `voting_mixin.py` |
| Resolution decisions, villainous choices and combat recipients | `resolution_choices_mixin.py` |
| Named choices, conditional payments and opening-hand entry | `source_choices_mixin.py` |
| Tokens, attacking entry, Sagas and cast tracking | `tokens_sagas_mixin.py` |
| Day/night, Planechase, schemes and dungeons | `variant_systems_mixin.py` |
| Resolving keyword actions | `keyword_actions_mixin.py` |
| Monarch, initiative, Ring and emblems | `designations_mixin.py` |
| Object-selection validation and resumable picks | `object_selection_mixin.py` |
| Applying actions to selected objects | `chosen_object_actions_mixin.py` |
| Retargeting, mutate and stack movement/countering | `stack_interaction_mixin.py` |
| Ward, conditional counter payments and combat-triggered keywords | `ward_combat_mixin.py` |

These mixins share engine state through `self`; choice decorators register the
same continuation methods when imported by the composition. Shared predicates,
constants and serialized-branch helpers live in `misc_helpers.py` and remain
re-exported from `misc_mixin.py` for existing callers.

## Identity and snapshots

- Room-name searches freeze the names of currently unlocked controlled doors
  into the choice's `not_names` card criteria. A library Room has both names;
  sharing either excludes it. A battlefield Room with both doors locked has
  neither name. The search's frozen list survives clone and subsequent door changes.

- Cloning a state with deferred resolution effects retains its event-log prefix.
  Active "this way" measurements use absolute log offsets; pruning older events
  during a paused choice would change those measurements after undo/clone.

- A self-scoped `RETURNED_TO_HAND` trigger is inferred to function in hand
  (`functions_from_hand`, RULE 113.6k). Its origin remains an event filter;
  graveyard returns, Dredge and battlefield bounce therefore stay distinct.
  Entry triggers receive the entrant's owner as well as its controller, so
  "from your graveyard" need not mean "under your control". Attachment effects
  can use `check_control=False` for untargeted, non-equip attachment instructions.

- Damage events share a `damage_batch_id` for one simultaneous damage
  occurrence. Batch-scoped prevention may enqueue `prevention_payoffs` on the
  damage ledger; their `settle_prevention(context)` runs after every recipient's
  replacement choices finish. This retains one-use prevention across all player
  recipients and creates the total replacement tokens simultaneously. A later
  damage step receives a different ID; cloning retains the pending payoff state.

- `GameObject.is_blocked` records RULE 509.1h independently of `blocked_by`.
  Removing the last blocker preserves blocked status for damage, activation,
  unblocked triggers and ninjutsu; leaving combat or starting a new zone visit
  clears it. Clone and the wire view retain the flag.
- Continuous-control eligibility resets at the controller's turn beginning,
  including phased-out permanents and skipped untap steps. Haste does not bypass
  an explicit "controlled since the beginning of your most recent turn" gate.

- Counter-removal events capture the affected zone visit and occur only for actual removals. Suspend last-counter casts and ordinary removal payoffs resolve as separate triggers. Resolution play choices retain exact exile visits through JSON snapshots. Suspend haste is a timestamped continuous grant until control loss; explicit end-of-turn cast grants use their own duration.

- Objects keep a stable `instance_id` plus a monotonic `zone_incarnation` that
  identifies one zone stay (RULE 400.7). Remembered/linked references (exile until
  departure, delayed graveyard returns, cast-cost IDs, event snapshots) compare
  incarnations, so leaving and re-entering a zone breaks the link.
  `zone_visit_counters` preserves counter LKI for departed source visits;
  resolving amounts and conditions use it only after that source visit ends.
  Source characteristic amounts use `zone_visit_characteristics` for the departed
  battlefield visit (RULE 608.2h), never a later incarnation of that physical card.
  `zone_visit_sources` preserves departed damage-source characteristics, including
  temporary keywords, through clone and token removal. Contextual trigger amounts
  use a binder-resolved event field and its captured zone visit, distinguishing
  the damage dealer from the damaged permanent.
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
  `game/linked_exile.py` is the shared reader for counts, Imprint, borrowed
  abilities, linked selections and play permissions. Remembered IDs only
  narrow that reader; they never restore a severed link. Casting-cost and
  as-enters links transfer once from the spell to its resulting permanent.
  Historical "exiled this way" counts remain separate from live linked counts.
  Standing play grants are read from the current source and controller;
  resolving grants freeze the linked pool and outlive their source. Without
  duration wording, cast/play offers exist only during resolution, including
  land plays through the ordinary land-limit checks (RULE 608.2g).
- Token-copy keyword exceptions belong to the copiable card before entry;
  separate "gains haste" instructions remain grants on the resulting tokens.
  Copy creation shares the state-owned token callback protocol: replacement
  and entry choices finish before riders, remaining copies and delayed removal.
  Enter-as-copy spell/token records reconstruct their continuation after cloning.
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
  Temporary exact-card play permissions also cover graveyard and library
  visits, independently of owner or library position. Mill/reveal pairs use
  the shared casting-window grammar; ordinary costs, timing, land limits and
  cast prohibitions still apply. No-duration offers remain resolution-local.
- Saga completion checks chapter abilities waiting for stack placement as
  well as those already on the stack (RULE 704.5s / 715.4). An unrelated
  trigger or a chapter from an older source visit does not protect a Saga.

## Resolution

- Source-granted quoted abilities use the same duration and exact-object
  grant statics as other grants. Nested quoted statics resolve controller-relative
  groups and supported attachment scopes from the recipient. Nested layer-6
  effects join the same timestamp/dependency worklist; granted static effects
  use the later host/grant timestamp and cease when their ability is removed.
  Attachment changes update timestamps; reattaching to the current host does not.
  Granted mana choices accept arbitrary printed
  pip alternatives; searches share the rules-backed subtype vocabulary
  and intersect it with any additional card-type restriction. Printed
  Changeling and unconditional all-creature-type CDAs apply to searched
  cards, using the shared model vocabulary; conditional or granted text
  does not become a printed CDA.

- Competing graveyard replacements (RULE 616.1): `_move_to_graveyard` collects every applicable redirect into outcome
  classes. Plain exile (Rest in Peace, Leyline, Yawgmoth's Will, Lurrus/free-cast exile, finality counters, "would die,
  exile it instead") is one class; Dauthi Voidwalker's exile-with-void-counter is another; "shuffle/put it into its
  owner's library instead" (Colossus/Nexus-style self statics, read off the bound statics so they work from any zone,
  plus the granted battlefield flag) is a third. The library class is always taken (the controller's beneficial
  replacement, the engine's default): an interactive exile-vs-library prompt would have to suspend the move mid-funnel
  and is not offered. Plain vs void exits to exile at once and leaves only the marker to a `graveyard_replacement`
  choice, an SBA prompt (like 903.9a) to the controller (owner off the battlefield), one per chooser for a simultaneous
  batch, answered with the proliferate wire shape (`selection_id` + `option_ids`, any subset of cards); the default
  (decline, bots, non-interactive) is none. Same-outcome sources and tokens never ask. 614.15 self-replacement does not
  apply (static abilities, not a spell's own instructions). Every game-event move into a graveyard goes through the
  funnel, including countered and fizzled spells, random discard, surveil and other library-to-graveyard moves (causes
  such as `countered`, `fizzled`, `unentered`, `discard`, `mill`). Only bookkeeping restores bypass it: undo, replay
  import and `edit_*`. A card already in exile that would go to a graveyard stays in exile under a plain-exile
  replacement, with no second visit or `EXILE` event (RULE 614.6).

- Proliferate (RULE 701.34a) stages recipient IDs/zone visits in its own
  `pending_choice`. Individual option IDs remain valid for bots; clients may
  atomically submit `choose` with `option_ids` and the matching `selection_id`.
  The empty list is legal. Each repeat has a fresh selection identity.
  Counter replacement continuations use state-owned receipts, and a deferred
  placement effect finishes ordering before another proliferation or rider.
  The perspective view adds `recommended_ids` from the same public counter
  utility used by Smart2; this annotation never mutates the pending engine
  choice or applies counters.

- Aggregate target limits share power and mana-value axes across casting,
  activation, trigger choices, copied targets and board metadata. Any-number
  trigger groups use their legal pool, with no fixed target cap. Partial
  trigger announcements live in GameState for clone/undo. Multiple targeted
  graveyard returns reuse exact simultaneous entry batches; each entry
  choice finishes before later instructions, including source flicker.

- Deferred source flicker delays the whole shared blink, independently of
  its later return timing and entry data. Delayed self captures retain the
  original resolving visit, including when the source left before arming.
  RULE 400.7j allows a delayed self return to capture the exact exile visit
  produced earlier in that same resolution; the saved visit survives cloning
  and never follows a subsequent return to exile (RULE 603.7c).
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
  Source-bound control windows validate the resolving source's exact zone visit
  before starting (RULE 611.2b), combine control/tapped requirements, and can
  retain a live target filter (enchanted status or source-relative power).
  Target-only windows remain independent of the ability source. Each resolved
  control effect keeps its own timestamp/window even if its recipient already
  controls the permanent; ending one window exposes the latest surviving effect.

- Continuous lifetimes share `game/durations.py` across floating statics,
  control records, timed copy layers, prevention shields and exile play grants.
  Upkeep/end-step clocks expire before beginning-of-step triggers; next-turn-only
  play permissions remain inactive until the holder's next played turn. A
  condition-bound lifetime ends permanently, preserving exact source/affected
  visits; attachment triggers retain their original host and attachment generation.
  Duration grammar retimes only represented continuous effects in its own sentence.

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

- Activations with `tap_others` retain `cost_tapped_visits` on their firing
  event. Each entry names the paid object's ID and zone incarnation, keeping
  overlapping activations independent. A resolve-time characteristic read
  uses the live matching visit, otherwise `zone_visit_characteristics` for
  last-known battlefield values (RULE 608.2h).

- Catalogue Flashback keyword specs may retain a full cost such as
  `{1}{W}, Pay 3 life`. The mana component uses the existing Flashback cost
  path; the parsed nonmana component is checked before casting and retained
  before the card leaves the graveyard, then paid once during casting.
  Paying life is not a resolution effect and is not refunded if targets leave.

- Standing alternative costs support `zero_mana` plus `from_exile`. This
  changes the cost only; an independent exile-play permission is still
  required. Select the granted cost before moving the spell to the stack,
  then pay that captured cost so a zone restriction cannot lose its usage
  charge. Exile-scoped once-per-turn costs track the granting source's exact
  zone visit; locking a door does not reset usage, but leaving and returning does.

- Activation-history conditions read event-time characteristics: block events
  retain `related_colors` for each opposing creature; damage events retain
  `source_is_legendary` beside `source_is_creature`. Block history is scoped to
  the source's exact zone visit and current turn. A "you were attacked this
  step" gate scans declared player attacks only, stopping at the latest
  `STEP_BEGIN`; attacks on planeswalkers do not count as attacks on their owner.

- A counted additional return cost can encode `return_pick: ["x", "swamp"]`.
  `ActivationCost.return_pick_count=None` means the announced X. The selected
  distinct controlled Swamps travel through `sacrifice_choices` with the
  `verb="return"` offer; they return to their owners' hands during payment.
  Cast legality and the offered X maximum use the same pool. Divided damage
  can expose `total_from_x` for the targeting dialog's announced total.

- Unattach costs preserve the detached object's ID/zone visit and its former
  host's derived subtypes on the activation's `trigger_event`
  (`unattached_source_id`, `unattached_source_incarnation`,
  `unattached_from_subtypes`). Later reattachments and activations cannot
  overwrite that payment's history; Changeling uses the derived type vocabulary.

- Convoke plans matching colored, hybrid and generic contributions together
  (`convoke_payment.plan_convoke`), preserving scarce colors rather than spending
  multicolored helpers greedily. Preview and payment share the plan; contributions
  never become mana or inflate mana-spent records.
- `ActivationCost.activation_zones` explicitly permits the same ability in hand,
  graveyard or battlefield. Off-battlefield ownership and battlefield control are
  checked separately; omitted zones retain the normal inferred behavior.
- Granted activated costs may use `tap_grant_source` to tap the granting permanent
  as well as the host. `add_counters(grantor_subject=True)` retains that grantor's
  exact visit. `create_turn_trigger(bake_source_object=True)` similarly captures
  the original source for a delayed body instead of a later incarnation.

- Emerge (RULE 702.119a,c) uses `alt_cost=True` and the existing `sacrifice_choice` instance ID. `_emerge_payment` validates the creature, includes commander tax and applies its mana-value reduction before cost floors. Payment records sacrifice characteristics through `note_sacrificed`; `emerge_cost_paid` gates the existing condition/override composition. A normal recast clears the flag.
- Crew (RULE 702.122b,c) records payment-time subtypes and exact creature visits. Historical counts include departed creatures; target filters require the original live visit. The turn reset clears both histories, and source-visit snapshots preserve them for resolving abilities after departure.
- "As ~ enters, choose ..." answers are state-owned: `GameState.pending_enter_choice` (object + zone visit) with the `pending_permanent_entry` / `pending_land_entry` / `pending_token_entry` record naming the entry path; `RulesEngine._take_enter_choice`/`_enter_choice_exit` re-derive the open effect, the remaining `enter_choice_effects` queue and the exit from them, so undo/clone onto an open choice still enters the permanent (RULE 614.12, 400.7; a changed zone visit enters nothing). New entry paths set one of the records instead of capturing a closure.
- Announced kicker conditions use the pending cast choice before target selection and the persisted kicker count afterward. Cast offers may provide a complete `kicker_variant` with distinct requirements. `damage_divisions` maps requirement indices to positive integer shares in target order; validate before paying, preserve shares on the private stack effects and their bound specs, and never redistribute shares when a target becomes illegal. Lazy composite branches pin source references to the resolving source visit.

- Open Ward payments retain their exact `StackItem`, payer and resolved cost in
  `GameState.pending_ward` (RULE 702.21a/b). Clone/undo preserves that identity;
  resumption consumes the descriptor and checks stack membership before payment
  or countering. X is fixed when Ward resolves, before the payment prompt.
- Outside-game cards (RULE 400.11) live in `Player.sideboard`, outside all
  zones and generic object/target pools. A live `sideboard_cast_permission`
  admits owned nonland cards through ordinary casting; successful commitment
  removes outside membership and preserves the instance ID. Sideboard views
  remain owner-private even when hands are revealed or another player controls
  the turn (RULE 724.4/5); turn controllers receive uniform opaque selections
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
- A sacrifice cost with several slots (`ActivationCost.sacrifice` / `sacrifice_also` / `sacrifice_more`, a counted
  `sacrifice_count`, `sacrifice_with_self`; grammar in `catalogue/sacrifice_clause.py`) is paid by
  `ActivationMixin._sacrifice_group_plan`: one distinct permanent per slot (RULE 701.17a), the source never among the
  chosen ones when it is sacrificed too. The legal action's `sacrifice_cost.slots` lists one option list per pick and
  the board answers with `tap_choices` in that order (the carrier `sacrifice_count` always used). Words that read the
  source (`named:~`, `chosentype`, `attached`) go through `continuous.matches_permanent_word(..., source)`; every other
  cost consumer (ward, additional / alternative cast costs, the mana planner) refuses `sacrifices_a_group`.
- Reveal-X, untap-others and counter-from-another costs (PAR-247) reuse the same contract: `reveal_cost` (count `x`,
  answered with `hand_card_choices`; revealing publishes through `GameState.reveal_card` and moves nothing),
  `tap_cost` with `untap: true` (answered with `tap_choices`; `ActivationCost.untap_others`, the `{Q}` source excluded),
  and `counter_cost` (one option per holder and counter kind, answered with `counter_choice` + `counter_kind`;
  `ActivationMixin._counter_removal_plan` validates it and removes through the rules primitive).
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

- Blocking restrictions that change the rules rather than characteristics must
  follow the live controlled creature group (RULE 611.2c). `WarCryRestriction`
  is an end-of-turn floating static consulted by `can_block`; its chosen-creature
  exception captures the exact battlefield incarnation, so blinking loses the
  exception while later arrivals and control changes remain subject to the rule.
- Instant/sorcery Splice (`splice_ids`, ordered distinct hand instance IDs)
  reveals the cards at commitment, adds their mana costs before reductions,
  and appends freshly bound effects after the host spell's text. Stack items
  retain this text for copying/clone; the host object loses the announcement
  after casting, so a later cast does not inherit it (RULE 702.47). The card
  remains in hand. Free and alternative host costs still pay Splice; legal
  actions, session dispatch, and board controls retain the selected IDs.
- `RulesEngine.exile(..., face_down=True)` stamps face-down status before
  announcing exile. `face_down_exile_viewers_explicit` makes an empty viewer
  set mean nobody may look (RULE 406.3), rather than the legacy owner-visible
  default. Session views hide identity while retaining public counters; the
  permission marker is cleared when the card leaves its exile visit.
- The Salubrious Philosopher reuses the optional draw-dig continuation with
  `categories=salubrious` and random bottom ordering. Its card-specific
  predicate reads printed Oracle instructions, including conditional/modal
  abilities, rather than deck-role tags. Basic land types supply inherent
  mana abilities; reminder text does not. Removal requires an instant/sorcery
  with damage (including fight), destruction, or exile that can affect an
  opposing permanent, excluding own-only objects and cards in other zones.
  Win condition uses printed mana value at least six.
- Suspended resolution tails retain their firing event alongside source visit
  and per-resolution receipts, restoring the outer event after resumption.
  This preserves Megatron's pre-replacement excess decision across damage
  replacement choices and clone/undo. Its split uses RULE 120.4a before damage
  modifiers, deals both portions simultaneously, then converts as specified in
  the [BRO release notes](https://magic.wizards.com/en/news/feature/the-brothers-war-release-notes).

- A Siege catalogue static may mark `preserve_siege_named_mode` to carry its
  named choice through defeat, exile, and the transformed cast. This supports
  the Dragon Brothers playtest card's Saga chapters referring back to Bolas
  or Ugin. The marker is inspected before resetting the defeated object;
  normal exile/return still clears the choice and the Battle chooses anew.

- Siege defeat can select an instant/sorcery back face in exile for the
  transformed cast (RULE 310.12b / 712.8a). It uses face rebinding instead
  of permanent transformation, which still rejects such a face (701.27e).
- Alara's two qualifying exile hits stay distinct from its passed-over
  cards: declining the cast leaves the unchosen hit exiled; only misses
  return to the bottom, with ordering driven by the replay RNG. Awaken the
  Maelstrom chooses its untargeted copy and counter recipients at resolution.
  Counter allocation finishes before placement; replacement choices retain
  the simultaneous batch and resume all recipients before destruction.
