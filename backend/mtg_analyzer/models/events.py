"""Game events — the currency of the effect system (RULE 603/614).

Reference: docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2/3 — events drive
triggered abilities and are what replacement effects rewrite).

An event is a *would-happen* description carried through the engine:
triggered abilities inspect events to decide whether they fire, and
replacement effects can rewrite an event (or cancel it) before it
actually resolves. Keeping events as plain typed data — a string ``type``
plus a ``data`` dict — is the parameter-based half of the hybrid design
in docs/07 PART 4: new event kinds need no new class.
"""

from __future__ import annotations

from typing import Any


class EventType:
    """Well-known event type names fired by the engine."""

    # Phase/step structure (RULE 500).
    PHASE_BEGIN = "PHASE_BEGIN"
    PHASE_END = "PHASE_END"
    STEP_BEGIN = "STEP_BEGIN"
    STEP_END = "STEP_END"
    TURN_BEGIN = "TURN_BEGIN"
    TURN_END = "TURN_END"
    UNTAP = "UNTAP"
    #: A permanent transitions untapped → tapped (RULE 701.21b) — fired once
    #: per genuine transition (not a no-op re-tap), and *not* for a permanent
    #: that enters the battlefield already tapped (RULE 614.1's tapped-entry
    #: conditions set `tapped` directly rather than going through this — a
    #: permanent entering tapped was never "not tapped" in the same turn, so
    #: it doesn't trigger a "becomes tapped" ability; see the real-card
    #: ruling for e.g. Kambal-style triggers, and Dionus, Elvish Archdruid's
    #: "whenever this creature becomes tapped").
    TAPPED = "TAPPED"
    #: The mirror image of `TAPPED`: a permanent transitions tapped →
    #: untapped (RULE 701.22), fired once per genuine transition by
    #: `RulesEngine.set_tapped` — every real untap route (the untap step's
    #: own per-permanent loop, an ability's own ``{Q}``/"Untap ~" cost or
    #: effect, `TapEffect`'s ``untap=True`` mode) funnels through that one
    #: choke point, same as `TAPPED` does for the other direction. Not
    #: fired for a permanent merely *entering* untapped (RULE 400.7 — a new
    #: object was never "tapped" to begin with) or for a zone-change reset
    #: (`GameObject.reset_as_new_object`/a fresh battlefield arrival simply
    #: setting `tapped = False` directly, outside `set_tapped`). Carries
    #: ``instance_id``/``controller_id`` exactly like `TAPPED`, closing the
    #: one deliberate gap `parser/oracle/segmenter.py`'s `_TRIGGER_VERBS`
    #: used to document under "becomes untapped" (MEC-43 round 4E,
    #: Mesmeric Orb — RULE 603.2's "whenever a permanent becomes untapped").
    UNTAPPED = "UNTAPPED"
    #: A permanent was tapped *to produce mana* (RULE 605.1) — fired by
    #: `GameEngine.tap_for_mana` after the mana lands in the pool, in addition
    #: to (and distinct from) the plain `TAPPED` transition. Carries
    #: ``instance_id`` + ``object_types`` (so a "taps a land"/"taps a nonland
    #: permanent" filter works via the ordinary `"group"` subject machinery),
    #: ``controller_id`` = the player who tapped it (RULE 605.1's "you"/"a
    #: player"), and ``produced`` (the ``{colour: n}`` mana it made, for a
    #: future "add one mana of any type that permanent produced" — Kinnan).
    #: Only genuine mana-ability taps fire this, never a plain tap-cost or an
    #: attack, which is what a "tapped for mana" trigger (Price of Glory, Wild
    #: Growth, Mana Web) needs to tell the two apart.
    TAPPED_FOR_MANA = "TAPPED_FOR_MANA"
    #: A player activated an ability of a permanent (RULE 602.2) — fired by
    #: `GameEngine.activate_ability` right after the ability item is put on
    #: the stack. Mana abilities (RULE 605.1a) never reach this: they never
    #: use the stack at all, resolving instead through `tap_for_mana`/
    #: `activate_hand_mana_ability`, which don't fire this event — so every
    #: firing of this one is inherently "isn't a mana ability" with no extra
    #: filter needed (Harsh Mentor/Immolation Shaman-shaped punisher cards).
    #: Carries ``instance_id``/``object_types`` (the permanent whose ability
    #: was activated) and ``controller_id`` = the activating player, the same
    #: RULE 603.1 ``"group"`` subject convention `TAPPED_FOR_MANA` uses.
    ACTIVATED_ABILITY = "ACTIVATED_ABILITY"

    # Object/zone movement.
    DRAW = "DRAW"
    #: A player would draw ``count`` cards as one instruction (RULE 120.3 —
    #: by default each card in a multi-card draw is its own independent
    #: instance of "drawing a card," so an ordinary replacement (a doubler,
    #: the empty-library win-instead shield) reads the per-card `DRAW`
    #: event below, one call per card, exactly as it always has). Fired
    #: once per `RulesEngine.draw()` call, *before* it's split into that
    #: many per-card `DRAW` events, for the rare replacement that cares
    #: about the whole attempted instruction rather than one card in it
    #: (Alms Collector's "if an opponent would draw **two or more**
    #: cards" — MEC-32). Carries ``player_id`` and ``count`` (the
    #: requested total); kept as its own event type so it can never
    #: double-apply an ordinary per-card `DRAW` replacement by also
    #: matching here.
    DRAW_INSTRUCTION = "DRAW_INSTRUCTION"
    DISCARD = "DISCARD"
    #: A single card was discarded (RULE 701.8) — fired once per card by
    #: every discard site (`RulesEngine.discard`/`discard_specific`/RULE
    #: 614.12's "discard a land instead"), in addition to (and after) the
    #: plain aggregate `DISCARD` above, which only ever carries a batch
    #: ``count`` — the same "aggregate event, plus a per-card sibling"
    #: convention `MILL`/`MILL_CARD` already established. Carries
    #: ``player_id`` and ``instance_id``, so "whenever you discard a card,
    #: exile **that card** from your graveyard" (MEC-38, Necropotence) has
    #: a real object to point at (`effects.ExileEffect`'s own
    #: ``target_kind="trigger_subject"``).
    DISCARD_CARD = "DISCARD_CARD"
    ENTERS_BATTLEFIELD = "ENTERS_BATTLEFIELD"
    LEAVES_BATTLEFIELD = "LEAVES_BATTLEFIELD"
    DIES = "DIES"
    #: A creature (``target_id``, controlled by ``controller_id``) would die —
    #: be put into a graveyard from the battlefield (RULE 700.4) — fired
    #: pre-emptively by `RulesEngine._move_to_graveyard` (creatures leaving
    #: the battlefield only) so a "if ~ would die, exile it instead"
    #: replacement (RULE 616.1, Gloomshrieker/Corpseweaver Prodigy,
    #: `game/effects.py`'s `_die_to_exile_replacement`) can redirect it to
    #: exile before any DIES trigger fires. Distinct from DIES above, which
    #: fires *after* the death has happened (a trigger source), and from
    #: DESTROY (only the "destroy" path, not every graveyard-from-battlefield
    #: move this one covers).
    WOULD_DIE = "WOULD_DIE"
    #: A permanent (``target_id``) would be destroyed (RULE 701.6) — fired
    #: pre-emptively by `RulesEngine.destroy` so a replacement effect can
    #: intercept it, chiefly a regeneration shield (RULE 701.16,
    #: `RulesEngine.regenerate`). Not fired by the *other* ways a permanent
    #: reaches the graveyard (0 toughness, sacrifice, discard, …) — RULE
    #: 701.16c/704.5f: those aren't "destruction" and regeneration can't
    #: replace them.
    DESTROY = "DESTROY"
    MILL = "MILL"
    #: A single *nonland* card was milled (RULE 701.13) — fired once per
    #: qualifying card by `RulesEngine.mill`, in addition to (and after) the
    #: plain aggregate `MILL` above, which only ever carries a batch
    #: ``count``. The "whenever a player/an opponent mills a nonland card"
    #: trigger family (RULE 728's Glowing One/Infesting Radroach, and The
    #: Wise Mothman's "whenever one or more nonland cards are milled" —
    #: simplified to this same per-card firing, since "put a +1/+1 counter
    #: on each of up to X target creatures" and "for each of N chances,
    #: optionally put a counter on up to one target creature" reach the same
    #: board states; see `game/ability_catalogue.py`) needs to tell a
    #: nonland card apart from a land one, which the aggregate event can't
    #: do without a live board lookup. Land mills don't fire this at all —
    #: no real card needs a "mills a land card" trigger yet, so there's
    #: nothing to filter for a hypothetical one; add an ``object_types``
    #: payload and widen this docstring if one ever does. Carries
    #: ``player_id`` (whose library it came from) and ``instance_id``.
    MILL_CARD = "MILL_CARD"
    #: A permanent was sacrificed (RULE 701.17) — fired *in addition to*
    #: DIES/LEAVES_BATTLEFIELD by `RulesEngine._move_to_graveyard` when the
    #: move's ``cause`` is a sacrifice (every `put_into_graveyard` caller: a
    #: cost-payment sacrifice, `sacrifice`/`SacrificeSelfEffect`). Carries the
    #: same ``object``/``owner_id``/``controller_id``/``instance_id``/
    #: ``object_types`` payload as DIES, so "whenever a player sacrifices a
    #: permanent" (Mayhem Devil) can be told apart from a plain death — a
    #: sacrificed creature fires both DIES and SACRIFICE, a sacrificed
    #: noncreature only SACRIFICE.
    SACRIFICE = "SACRIFICE"
    #: A Saga (RULE 714) reached a new lore-counter count — carries
    #: ``instance_id`` (which Saga) and ``chapter`` (the new count), so a
    #: chapter ability's triggered condition can scope to both itself and
    #: the specific chapter number(s) it covers.
    #: One or more counters would be put on a permanent (RULE 122) — fired
    #: pre-emptively by `RulesEngine.add_counters` (only for counters being
    #: *placed*, never removed) so a "put twice that many instead" replacement
    #: (e.g. Doubling Season, RULE 616.1) can rewrite the ``amount`` before
    #: any counter actually lands.
    COUNTER = "COUNTER"
    #: One or more tokens would be created under a player's control (RULE
    #: 111.5) — fired pre-emptively by `RulesEngine.create_token` (battlefield
    #: entries only) so a "create twice that many instead" replacement (e.g.
    #: Doubling Season, Parallel Lives) can rewrite the ``amount`` before any
    #: token exists.
    CREATE_TOKENS = "CREATE_TOKENS"
    SAGA_CHAPTER = "SAGA_CHAPTER"
    #: A battle lost its last defense counter (RULE 310.11b) — carries
    #: ``instance_id`` and ``controller_id``. This is what a Siege's own
    #: intrinsic "when the last defense counter is removed from this
    #: permanent" ability watches, and what "whenever a battle you protect
    #: is defeated"-style cards would hang off. Noticed by the SBA pass
    #: (`RulesEngine.check_state_based_actions`) rather than at any one
    #: counter-removal site, so damage and a bare "remove a defense counter"
    #: effect reach it alike.
    BATTLE_DEFEATED = "BATTLE_DEFEATED"
    #: A Class (RULE 716) reached a new class level — carries ``instance_id``
    #: and ``chapter`` (the new level), the same convention as SAGA_CHAPTER,
    #: so a rare "when this Class becomes level N" trigger can scope by both.
    CLASS_LEVEL = "CLASS_LEVEL"
    #: RULE 702.140b: a mutating creature merged onto a host — carries
    #: ``instance_id`` (the surviving merged permanent, which per RULE
    #: 702.140c is the *same* permanent, never a new object) and
    #: ``controller_id``. "Whenever this creature mutates" (Lore Drakkis)
    #: triggers off it; deliberately distinct from ENTERS_BATTLEFIELD, which
    #: mutate specifically does *not* fire.
    MUTATES = "MUTATES"
    #: A player scried (RULE 701.18): looked at the top N of their library and
    #: reordered / bottomed them.
    SCRY = "SCRY"
    #: A player surveiled (RULE 701.31): looked at the top N of their library
    #: and put any number of them into their graveyard, the rest staying on
    #: top in any order (no bottoming option, unlike SCRY).
    SURVEIL = "SURVEIL"
    #: A permanent explored (RULE 701.44b) — fired after the whole process
    #: (reveal top card; land → hand, else +1/+1 counter + may bin the
    #: revealed card), even if some or all of it was impossible. Carries
    #: ``instance_id`` (the exploring permanent), ``controller_id``, and
    #: ``found_land`` (bool). For "whenever ~/a creature you control
    #: explores, <effect>" (Wildgrowth Walker/Path of Discovery-shaped).
    EXPLORED = "EXPLORED"
    #: A card was moved to exile (RULE 406) — e.g. cascade/discover reveal.
    EXILE = "EXILE"
    #: The Ring tempted a player (RULE 701.51a, Tales of Middle-earth) —
    #: fired by `RulesEngine.the_ring_tempts_you` after the emblem levels up
    #: and the Ring-bearer choice resolves, for "whenever the Ring tempts
    #: you, <effect>" triggers (Aragorn, Company Leader/Galadriel of
    #: Lothlórien/Sméagol, Helpful Guide-shaped). Carries ``player_id`` (the
    #: tempted player), same convention as SCRY/SURVEIL.
    RING_TEMPTED = "RING_TEMPTED"
    #: A player searched their library (RULE 701.19) / shuffled it (RULE 701.20).
    LIBRARY_SEARCHED = "LIBRARY_SEARCHED"
    SHUFFLE = "SHUFFLE"

    # Spells/abilities. SPELL_CAST carries ``free=True`` when the spell was
    # cast without paying its mana cost (RULE 118.9 — cascade/discover/etc.),
    # so a "cast" trigger can distinguish a normal cast from a free one; a
    # spell put onto the battlefield instead (never cast) fires only
    # ENTERS_BATTLEFIELD, never SPELL_CAST.
    #
    # It also carries ``mana_spent`` — how much mana was actually paid for it
    # (RULE 202.1/601.2h), which is *not* the same as ``free``: a spell cast
    # for an alternative cost of {0} (Ornithopter, a Pact, a free-cast
    # permission) had mana "spent" of 0 while still being a paid cast, and a
    # spell whose cost was reduced to {0} likewise. "If no mana was spent to
    # cast it" (Lavinia, Azorius Renegade / Boromir, Warden of the Tower)
    # reads exactly this key via a trigger ``filter``; also stamped onto the
    # object itself as `GameObject.mana_spent_to_cast`, since a resolving
    # effect can need it after the spell has left the stack.
    SPELL_CAST = "SPELL_CAST"
    SPELL_RESOLVED = "SPELL_RESOLVED"
    LAND_PLAYED = "LAND_PLAYED"
    #: RULE 702.28c: a card was cycled (its Cycling cost paid, discarding
    #: it — `ActivationCost.is_cycling` distinguishes this from Channel's
    #: own, unrelated ``discard_self`` cost). What a "When you cycle this
    #: card, `<effect>`." triggered ability watches for; carries
    #: ``instance_id``/``controller_id`` like every other self-scoped
    #: object event.
    CYCLED = "CYCLED"

    # Combat / damage / life.
    DAMAGE = "DAMAGE"
    #: A player would gain life (RULE 119.3) — fired pre-emptively by
    #: `RulesEngine.gain_life` (positive amounts only) so a "you gain that
    #: much life plus N / twice that much instead" replacement (RULE 616.1,
    #: e.g. Angel of Vitality/Boon Reflection) can rewrite the ``amount``
    #: before any life is actually gained. Carries ``player_id`` (the
    #: gaining player) and ``amount``. Distinct from LIFE_GAINED below,
    #: which fires *after* the gain has happened (a trigger source, not a
    #: replaceable pre-event).
    LIFE_GAIN = "LIFE_GAIN"
    LIFE_GAINED = "LIFE_GAINED"
    LIFE_LOST = "LIFE_LOST"
    ATTACKS = "ATTACKS"
    BLOCKS = "BLOCKS"
    #: An attacker goes from unblocked to blocked (RULE 509.5) — fired once
    #: per attacker (never once per blocker), the moment its ``blocked_by``
    #: transitions from empty to non-empty within one `declare_blockers`
    #: call, carrying ``blocker_count`` (the final count) for keywords whose
    #: trigger amount scales with it (rampage). Distinct from `BLOCKS`, which
    #: fires per *blocker* and scopes to the blocker's own controller/type —
    #: afflict/bushido/rampage (RULE 702.130/702.45/702.23) all trigger off
    #: the *attacker* becoming blocked, which `BLOCKS` alone can't express.
    BECOMES_BLOCKED = "BECOMES_BLOCKED"
    #: MEC-19/RULE 115/601.2c: an object or player was named as a target when
    #: a spell or ability's targets were finalized — fired once per target by
    #: `RulesEngine.check_ward` (renamed from a ward-only check to the general
    #: RULE 601.2c/602.2b/603.3d "targets finalized" choke point every
    #: spell/activated-ability/triggered-ability call site already reaches
    #: unconditionally; ward itself is unchanged, still its own direct
    #: cast-time check, not rewired onto this event). Powers RULE 603.1's
    #: "whenever ~ becomes the target of a spell/ability [an opponent/you
    #: control(s)], …" family (Goldspan Dragon/Tectonic Giant/the ~150-card
    #: un-keyworded-Ward-shaped "counter it unless that player pays" cycle —
    #: a card that instead prints the real **Ward** keyword is already
    #: MODELED through the keyword catalogue and never reaches this event's
    #: trigger grammar at all, since it has no "whenever…becomes the
    #: target…" sentence of its own to parse).
    #:
    #: For a `GameObject` target: ``instance_id`` (the RULE 603.1 default
    #: subject key — no `_SUBJECT_EVENT_KEYS` override needed) and
    #: ``target_controller_id`` (its controller, for a "group"
    #: subject's "…you control" scoping via `_GROUP_CONTROLLER_EVENT_KEYS`).
    #: ``is_player`` distinguishes a player target (``target_controller_id``
    #: is then ``None`` — a player has no controller); player-subject
    #: "whenever you become the target of…" triggers aren't wired yet (no
    #: shipped card needs one in isolation from a compound "you or a
    #: permanent you control" subject, itself a separate, un-built compound-
    #: subject grammar — BACKLOG.md).
    #:
    #: ``controller_id`` is the *targeting* spell/ability's controller (the
    #: caster), not the target's — what `effect_binder`'s new
    #: ``caster_relation`` predicate compares against the trigger's own
    #: source to tell "an opponent controls" from "you control". ``item_kind``
    #: is `StackItem.kind` (``"spell"``/``"ability"``), consumed through the
    #: ordinary ``"filter"`` exact-match mechanism to scope "of a spell" vs.
    #: "of a spell or ability" vs. "of an ability". ``stack_id`` is
    #: `StackItem.stack_id` — the only way a later-resolving effect
    #: (`CounterUnlessPayEffect`) can find back the exact spell/ability that
    #: did the targeting, since nothing else on this event survives a
    #: `GameState` deep copy the way a raw object reference would need to.
    BECOMES_TARGET = "BECOMES_TARGET"
    #: RULE 901.10: a player planeswalked **to** a plane — the plane that
    #: just turned face up is named by ``instance_id``/``plane``, and the
    #: planeswalking player by ``player_id``/``controller_id``. This is what
    #: a plane's own "When you planeswalk to ~, …" ability triggers off.
    PLANESWALKED_TO = "PLANESWALKED_TO"
    #: RULE 901.10: the mirror — a player planeswalked **away from** the
    #: plane named here, which is now face down at the bottom of the deck.
    PLANESWALKED_AWAY = "PLANESWALKED_AWAY"
    #: RULE 901.13: the chaos symbol came up on the planar die, so the
    #: face-up plane's "Whenever chaos ensues, …" ability triggers. Carries
    #: the rolling player as ``player_id``/``controller_id`` — the ability is
    #: controlled by whoever rolled (901.13a).
    CHAOS_ENSUED = "CHAOS_ENSUED"
    #: RULE 904.7: the archenemy set a scheme in motion (turned it face up),
    #: which is the trigger condition every scheme's own ability shares.
    #: Carries ``instance_id`` (the scheme) and ``player_id``.
    SCHEME_SET_IN_MOTION = "SCHEME_SET_IN_MOTION"
    #: RULE 309.4c: a player moved their venture marker into a room — the
    #: trigger condition every room ability shares ("When you move your
    #: venture marker into this room, …"), which is why the event carries
    #: ``player_id``/``dungeon``/``room`` rather than an ``instance_id``: a
    #: dungeon card is not a permanent and has no game object.
    DUNGEON_ROOM_ENTERED = "DUNGEON_ROOM_ENTERED"
    #: RULE 309.7: a player completed a dungeon (the card left the game).
    #: Carries ``player_id`` and ``dungeon`` (its name).
    DUNGEON_COMPLETED = "DUNGEON_COMPLETED"
    #: RULE 726.2/726.5: a player took the initiative — fired even when the
    #: player who took it already had it (726.5 says the designation isn't
    #: duplicated but the trigger still fires), which is what makes the
    #: inherent "whenever a player takes the initiative, that player ventures
    #: into Undercity" ability repeatable.
    TOOK_INITIATIVE = "TOOK_INITIATIVE"
    #: RULE 708.8: a face-down permanent was turned face up — by the RULE
    #: 702.37e/702.168d/701.40b/701.58b special action, or by any effect that
    #: turns one up. Carries ``instance_id``/``controller_id``/
    #: ``object_types`` (the *face-up* card's, since it has already regained
    #: its normal characteristics by the time this fires), so "when this
    #: creature is turned face up, …" (the morph trigger family) rides RULE
    #: 603.1's ordinary self/group subject scoping. Not fired by RULE 708.9's
    #: "reveal it as it changes zones" — that's a reveal, not a turn-face-up.
    TURNED_FACE_UP = "TURNED_FACE_UP"
    #: RULE 702.112b: a creature just became renowned (its Renown N ability
    #: fired for the first, only time) — carries ``instance_id``, so a
    #: card's own separate "when this creature becomes renowned, …" trigger
    #: (Relic Seeker) can key off it distinctly from Renown's own counter-
    #: placing effect (`game/effects.py`'s `RenownEffect`, which fires this).
    RENOWNED = "RENOWNED"
    #: RULE 701.37a: a permanent just became **monstrous** (its monstrosity
    #: ability resolved for the first, only time) — carries ``instance_id``
    #: and ``controller_id``, so "when ~ becomes monstrous, …" (Arbor
    #: Colossus, the largest trigger family on these cards) rides RULE
    #: 603.1's ordinary self/group subject scoping. Fired by
    #: `game/effects.py`'s `MonstrosityEffect`, and *only* on the transition:
    #: 701.37a's "if this permanent isn't monstrous" means a second
    #: activation does nothing at all, event included.
    BECAME_MONSTROUS = "BECAME_MONSTROUS"
    #: PAR-28 / RULE 719.3a: a Case just became **solved** — carries the
    #: Case's ``instance_id`` and ``controller_id``. Fired only on the
    #: transition (`BecomeSolvedEffect` guards on ``is_solved``). No card
    #: yet has a "when a Case is solved" trigger, but the event exists so
    #: one can be bound the same way as `BECAME_MONSTROUS`.
    SOLVED = "SOLVED"
    #: RULE 701.15a: a creature was just **goaded** by a player — carries the
    #: goaded creature's ``instance_id`` plus ``goader_id``/``controller_id``
    #: (the goading effect's controller, i.e. the player the creature must
    #: now attack around per 701.15b). Fired on every goad, including a
    #: re-goad by the same player that 701.15d makes a no-op requirement-wise
    #: — "whenever you goad a creature" cares that it happened, not whether
    #: the designation changed.
    GOADED = "GOADED"
    #: RULE 701.60a: a creature was just **suspected** — carries the
    #: creature's ``instance_id`` and ``controller_id``. Fired on every
    #: suspect, including one that changed nothing (RULE 701.60c —
    #: re-suspecting an already-suspected creature). A suspected creature has
    #: menace and can't block (701.60b), both read off `GameObject.
    #: is_suspected` at combat time (`combat.is_suspected`), not the event.
    #: No card yet triggers on "becomes suspected"; the event exists so one
    #: could bind the same way as `GOADED`.
    SUSPECTED = "SUSPECTED"
    #: RULE 506.4's "a player attacks you [with one or more creatures]" —
    #: an aggregate, once-per-combat event `ATTACKS` (fired once per
    #: *creature*) can't express on its own: a player attacking with 3
    #: creatures fires `ATTACKS` three times, never once with a count.
    #: Fired by `GameEngine._fire_player_attacked_events` the moment combat
    #: locks in (leaving the declare-attackers step — that step's additive,
    #: multi-call design has no other "I'm done" signal), once per
    #: (attacking player, defending player) pair that attacked at all this
    #: combat, carrying ``attacking_player_id``/``defending_player_id``/
    #: ``count`` (how many of that attacker's creatures targeted that
    #: defender) — direct player attacks only (``combat_defender["kind"] ==
    #: "player"``), not the "or a planeswalker you control" variant (no
    #: real card in this pool needs it yet).
    PLAYER_ATTACKED = "PLAYER_ATTACKED"
    #: RULE 506.5-adjacent "whenever ~ attacks alone" / "whenever a Samurai
    #: or Warrior you control attacks alone" — the *only* attacking creature
    #: this combat. Aggregate for the same reason `PLAYER_ATTACKED` is:
    #: `ATTACKS` fires per creature as it's declared, and `declare_attackers`
    #: is additive, so the first declaration of a two-creature attack would
    #: always momentarily look alone. Fired by `GameEngine.
    #: _fire_attacks_alone_event` once combat locks in (leaving the
    #: declare-attackers step), at most once per combat, carrying the same
    #: ``instance_id``/``player_id``/``object_types`` payload `ATTACKS` does
    #: so RULE 603.1's self/group subject scoping works unchanged.
    ATTACKS_ALONE = "ATTACKS_ALONE"
    #: RULE 603.1's "whenever **one or more** creatures you control [with
    #: `<characteristic>`] deal combat damage to a player" (Tifa, Martial
    #: Artist) — the combat-damage-step sibling of `PLAYER_ATTACKED`'s own
    #: "with one or more creatures" aggregate: the ordinary `DAMAGE` event
    #: fires once per *hit* (RULE 120.3), so a step where two qualifying
    #: creatures both connect would otherwise trigger a plain per-creature
    #: `DAMAGE`-subject condition twice, not once — wrong for a template
    #: that describes a single yes/no condition about the whole step, the
    #: same reasoning `PLAYER_ATTACKED`'s own docstring gives for `ATTACKS`.
    #: Fired by `GameEngine._apply_combat_damage`, once per (attacking
    #: creature's controller, player hit) pair that actually connected this
    #: step, carrying ``player_id`` (the "you control" half, matching every
    #: other aggregate event's convention), ``target_id`` (the player hit),
    #: and ``max_power`` — the highest power among that pair's contributing
    #: creatures, read live at the moment damage was dealt (RULE 613.1),
    #: for a "with power N or greater" qualifier to check without this
    #: event needing to name every contributing creature individually.
    CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER = "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"

    #: RULE 702.19b: a permanent with exert is actually exerted (its
    #: controller chose to, declaring it as an attacker). Carries the same
    #: ``instance_id``/``player_id``/``object_types`` payload as `ATTACKS`,
    #: so both a self-scoped "when you do" trigger and a group-scoped
    #: "whenever you exert a creature" one read it the same way every other
    #: RULE 603.1 subject-scoped event does. Fired by `GameEngine.
    #: declare_attackers`, after `ATTACKS`.
    EXERTED = "EXERTED"

    # Win/loss (RULE 104, RULE 704).
    PLAYER_WOULD_LOSE = "PLAYER_WOULD_LOSE"
    PLAYER_LOST = "PLAYER_LOST"


class GameEvent:
    """Something that is happening (or would happen) in the game."""

    def __init__(self, type: str, **data: Any) -> None:
        self.type = type
        self.data: dict[str, Any] = data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def copy_with(self, type: str | None = None, **overrides: Any) -> "GameEvent":
        """A copy with a possibly-different type and/or overridden data.

        Used by replacement effects, which produce a *new* event rather
        than mutating the original (RULE 614).
        """
        merged = {**self.data, **overrides}
        return GameEvent(type or self.type, **merged)

    def to_dict(self) -> dict[str, Any]:
        serializable = {
            k: v for k, v in self.data.items() if isinstance(v, (str, int, float, bool, type(None)))
        }
        return {"type": self.type, "data": serializable}

    def __repr__(self) -> str:
        return f"GameEvent({self.type!r}, {self.data!r})"
