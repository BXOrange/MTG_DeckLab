"""RULE 613.6 conditional static abilities — one whitelisted vocabulary for
"as long as `<condition>`, …", shared by every static that has a condition.

Why this module exists
----------------------
Conditional statics arrived one card at a time, and each one added its own
parameter to `continuous.group_selector_objects`: ``active_player_only``
("during your turn"), ``min_level``/``max_level`` (a Class/Leveler's own
counters), ``min_count_selector``/``min_count`` (Metalcraft). Each is a
separate ``if`` returning ``[]`` when inactive, and each needed its own key
in `effects._SELECTOR_KEYS`, which is exactly the trap that silently drops a
new selector param. "As long as" is not a rare shape — it leads ~250 clauses
in the card cache, across at least five families (the source's own state, an
attached permanent's characteristics, a board count, the turn, a player's
life/hand) — so the next dozen would have been the next dozen parameters.

This is the single evaluation path instead. A condition is a small clamped
dict ``{"kind": <whitelisted name>, …}`` carried in a static's ``active_if``
param and evaluated **live, every recompute**, against the ability's own
source and controller. It never caches: that is what makes "as long as ~ is
untapped" turn itself off the moment the permanent taps, with no event, no
trigger and no bookkeeping.

``active_if``, not ``condition``, because a ``combat_restriction`` static
already carries a ``condition`` of its own in the same params dict ("~ can't
attack **unless** defending player controls an Island") drawn from the
separate combat-time vocabulary below — one key holding two vocabularies
would make each fail closed on the other's dicts.

The legacy parameters above still work and are still spelled the same way in
every shipped `AbilitySpec` — `condition_from_legacy_params` translates them
into this vocabulary so there is one implementation, not two.

Fail-closed, like every other card-text-derived vocabulary in this package:
an unrecognized ``kind`` (or a malformed param) makes the condition *false*,
so an unmodeled static simply doesn't apply. It never raises, because it runs
inside the layer engine on every recompute.

Not to be confused with:

* `game/condition_query.py` — a *cast/activation legality* gate (RULE 702.8b
  flash, 606.3 loyalty timing), which must work for a card in hand and so
  can't be a battlefield-static concept;
* `parser/oracle/spec.py`'s ``_ALLOWED_CONDITION_KEYS`` — whether an
  already-resolving *one-shot* effect applies (RULE 702.33b "if kicked");
* `GameEngine._combat_condition_met` — "~ can't attack **unless** `<board
  condition>`", evaluated at combat time against a *defending player*, which
  no recompute-time condition can see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # models must not be imported at runtime (module boundary)
    from ..models.game.game_object import GameObject
    from ..models.game.game_state import GameState


#: Every recognized ``kind``. A condition naming anything else is false.
STATIC_CONDITION_KINDS: frozenset[str] = frozenset(
    {
        # -- The *subject*'s own state (the largest family by card count).
        # Historically these read the ability's own source and are still
        # spelled ``source_*`` in every shipped spec; which object they
        # actually read is now chosen by the condition's ``of`` key (see
        # `CONDITION_SUBJECTS`), defaulting to the source.
        "source_tapped",  # "as long as ~ is tapped"
        "source_untapped",  # "as long as ~ is untapped"
        "source_monstrous",  # RULE 701.37b
        "source_harnessed",  # MEC-79 / RULE 701.64b — the Infinity Stones' ∞
        "is_licid_aura",  # MEC-47 — this Licid is currently an Aura
        "not_licid_aura",  # MEC-47 — this Licid is still a creature
        "source_attacking",  # "as long as ~ is attacking"
        # PAR-28: RULE 702.142a Boast — "Activate only if this creature
        # attacked this turn." A per-object flag set in declare-attackers,
        # reset each untap step (unlike ``source_attacking``, which clears
        # the instant combat ends, RULE 511.3).
        "source_attacked_this_turn",
        # PAR-62: Raid's player-scoped declaration history, not Boast's
        # source-only flag.
        "you_attacked_this_turn",
        # PAR-28: RULE 702.169b/719.3b Solved — "As long as this Case is
        # solved, …" (and its activate-/trigger-only siblings). A permanent
        # designation that persists until the Case leaves the battlefield.
        "source_solved",
        # PAR-28: RULE 702.178a Max Speed — "As long as your speed is 4, …".
        # Reads the *controller*'s speed (RULE 702.179), no ``of`` subject.
        "your_speed_is_max",
        # PAR-28: RULE 702.57b Forecast — "Activate only during the upkeep
        # step of the card's owner." Used as an ``activation_condition`` only.
        "your_upkeep",
        "source_blocking",
        "source_paired",  # RULE 702.94b soulbond
        "source_attached",  # "as long as ~ is attached to a creature"
        "source_equipped",  # "as long as ~ is equipped"
        "source_enchanted",  # "as long as ~ is enchanted"
        "source_counters",  # + ``counter``/``min``/``max``
        # "for as long as you control ~" / "…as long as ~ remains on the
        # battlefield" — the lock-down family's own duration (PAR-11): the
        # effect lasts while its *source* is still around, which is not
        # automatic, since a RULE 611 continuous effect otherwise outlives its
        # source (611.2b).
        "source_on_battlefield",
        # -- The subject's *characteristics* (RULE 109.3), as opposed to its
        # state above. Printed almost exclusively about an attached permanent
        # ("as long as enchanted permanent is a creature"/"…is red"/"…is a
        # Vehicle"), i.e. with ``of="attached"`` — but the kinds themselves
        # are subject-agnostic like every other row here.
        "is_card_type",  # + ``card_type``
        "is_color",  # + ``color`` (a WUBRG letter)
        "is_subtype",  # + ``subtype``
        # PAR-117 (conditional-wrapper residue): RULE 205.4a's legendary
        # supertype, read off `GameObject.is_legendary` (the printed
        # supertype *or* a granted one) rather than `is_card_type`/
        # `is_subtype`, neither of which covers a supertype. "that creature
        # is legendary" (Ringwraiths) is the only printed phrasing so far —
        # no ``of`` default beyond the usual "source".
        "is_legendary",
        # RULE 205.4a's basic supertype, off the printed type line (a `Card`
        # has no flag for it) — "a basic land card" (Rowen, PAR-120).
        "is_basic",
        # PAR-117: "that creature wasn't dealt damage this turn" (Faller's
        # Faithful) — RULE 514.2 only clears `GameObject.damage_marked` at
        # cleanup, so nonzero marked damage at any other point in the same
        # turn is exactly "dealt damage this turn", with no separate
        # per-turn tracker needed.
        "was_dealt_damage_this_turn",
        # -- Whose turn it is (RULE 613.6's commonest non-board gate).
        "your_turn",
        "not_your_turn",
        # -- The board.
        "control_count",  # + ``selector``/``min``/``max`` — Metalcraft-shaped
        # "as long as you control a permanent of each color" (Spirit of
        # Resistance, PAR-78) — a devotion-shaped five-colour AND, not a
        # single-selector count.
        "control_permanent_of_each_color",
        "control_named",  # + ``name`` — "as long as you control a <card>"
        # "as long as an opponent has N or more cards in their graveyard" —
        # `control_count`'s opponent-scoped sibling: true when *any one*
        # opponent satisfies it, which is what "an opponent" means.
        "opponent_count",  # + ``selector``/``min``/``max``
        # -- The controller's own resources.
        "life_at_least",  # + ``amount``
        "life_at_most",
        # "as long as an opponent has N or less life" (Bloodghast, PAR-60) —
        # true when any one opponent satisfies it. + ``amount``.
        "opponent_life_at_most",
        "cards_in_hand_at_least",
        "cards_in_hand_at_most",
        # "at the beginning of each opponent's upkeep, if that player has N or
        # fewer cards in hand, …" (Davriel/Hellfire Mongrel/Shrieking
        # Affliction, PAR-120) — "that player" is whoever's step just began
        # (RULE 502.1's active player), not this ability's own controller;
        # `cards_in_hand_at_most`'s ``player = _controller(state,
        # controller_id)`` read would answer the wrong player's hand size for
        # this per-opponent trigger shape.
        "active_player_cards_in_hand_at_most",
        # "if you gained life this turn" (PAR-60) — reads
        # `GameState.life_gained_this_turn`; optional ``amount`` (default 1).
        "gained_life_this_turn",
        # "if you descended this turn" (RULE 700.11 — a permanent card was put into your
        # graveyard from anywhere: died, discarded or milled here; a countered spell is not seen) — reads `GameState.permanent_card_to_graveyard_this_turn`.
        "descended_this_turn",
        # "if a card left your graveyard this turn" (Primary Research, Relic
        # Retriever, PAR-60) — reads `GameState.cards_left_graveyard_this_turn`.
        "card_left_graveyard_this_turn",
        # "if an opponent controls more lands than you" (Land Tax,
        # Archaeomancer's Map, Claim Jumper, PAR-60) — true when any one
        # opponent's land count exceeds the controller's.
        "opponent_controls_more_lands",
        # PAR-120: the general form — some one opponent's count of a structured
        # ``selector`` exceeds the controller's ("an opponent controls more
        # creatures than you"). `opponent_controls_more_lands` is its special case.
        "opponent_has_more",  # + ``selector``
        # ENG-47: "…happened this turn" — how many events of the current turn match a
        # trigger-shaped ``trigger`` dict (the same ``event`` / ``condition`` /
        # ``filter`` keys a triggered ability of that shape carries), read off the
        # turn-stamped `GameState.event_log`. + ``min``/``max``. Replaces one
        # hand-kept `*_this_turn` tracker per phrase.
        "event_this_turn",
        # "if there are N or more <type> and/or <type> cards in your
        # graveyard" (Lorehold Archivist, PAR-60). + ``types`` + ``amount``.
        "graveyard_card_type_count_at_least",
        "distinct_mana_values_in_graveyard_at_least",
        # "if a player has one or fewer cards in hand" (Naktamun Lorespinner,
        # PAR-60) — any player. + ``amount``.
        "any_player_cards_in_hand_at_most",
        # "if you control no creatures with decayed" (Jadar, PAR-60). +
        # ``keyword``.
        "control_no_creatures_with_keyword",
        # PAR-30: "as long as there's a `<subtype>` card in your graveyard"
        # (the Avatar: TLA "Lesson" cards — Aang A Lot to Learn, Fire Nation
        # Cadets, First-Time Flyer, Platypus-Bear). + ``subtype`` (a
        # lowercase word matched against each graveyard card's type line,
        # the same `graveyard_has_type` `EffectSpec.condition` uses) and an
        # optional ``min`` (default 1). The always-active-player "you" read,
        # like every other resource row here.
        "subtype_in_graveyard",
        # MEC-46: "if another `<subtype>` entered the battlefield under your
        # control this turn" (Galadriel, Elven-Queen's RULE 603.4
        # intervening-if). + ``subtype`` — a live scan of the controller's
        # battlefield for a permanent other than the source whose type line
        # carries the word and that entered this turn (`GameObject.
        # turn_entered == state.internal_turn.number`, the same read
        # `condition_query.entered_this_turn` makes). No per-turn tracker
        # needed — the per-object entry flag already exists.
        "another_subtype_entered_this_turn",  # + ``subtype``
        "drawn_cards_at_least",  # + ``amount``; optional ``scope`` (you/opponents)
        "mana_color_spent_to_cast_at_least",  # + ``color`` + ``amount`` (Adamant)
        "treasure_mana_spent_to_cast",  # actual source-tagged mana payment
        "treasure_mana_spent_to_activate",  # the same, for the last activation
        # "…you've cast an instant or sorcery spell this turn" (PAR-10) —
        # `GameState.cast_instant_or_sorcery_this_turn`, reset for *every*
        # player each `begin_turn` (unlike `spells_cast_this_turn`'s
        # active-player-only reset) since this is read for a non-active
        # controller too (Leapfrog's granted flying, Haunting Figment's
        # evasion) as well as the always-active-player activation-condition
        # use (Hall of Oracles/Jin-Gitaxias — only reachable at sorcery speed
        # anyway, but the state itself must stay correct regardless).
        "cast_instant_or_sorcery_this_turn",
        "cast_noncreature_spell_this_turn",
        "control_legendary_subtype",
        # PAR-32 phase-trigger intervening-ifs (Cloakwood Hermit / Dragon
        # Cultist) — new per-turn `GameState` trackers.
        "creature_card_to_graveyard_this_turn",
        "you_dealt_damage_this_turn_at_least",
        # "At the beginning of each end step, if you put a counter on a
        # creature this turn, …" (Lasting Tarfire) — `GameState.
        # counter_placed_on_creature_this_turn`, a set of causer ids.
        "you_placed_counter_on_creature_this_turn",
        # MEC-60 (Acolyte of Bahamut): "The first `<subtype>` spell you cast
        # each turn costs `{N}` less to cast." + ``subtype`` — a
        # `cost_reduction` ``active_if`` gate, true only while `controller_
        # id` hasn't yet cast a spell of that creature subtype this turn
        # (`GameState.creature_type_spells_cast_this_turn`).
        "first_subtype_spell_this_turn",
        # -- The controller's designations (RULE 725/726/702.131c) — MEC-12.
        # No ``of`` subject: "you" in "as long as you're the monarch" always
        # means the static's controller, the same read `your_turn` already
        # makes.
        "is_monarch",  # "as long as you're the monarch"
        "has_initiative",  # "as long as you have the initiative"
        "has_city_blessing",  # "as long as you have the city's blessing"
        "has_enduring_story",  # "as long as you have an enduring story" (RULE 702.195b, PAR-51)
        # -- Subject-scoped predicates over an arbitrary object (ENG-36).
        # These carry no subject of their own: whichever object ``of`` names
        # (or, from `effect_conditions`, an effect-only referent such as the
        # clause's previous target) is the thing asked about. They exist as
        # one row each instead of one row per (predicate × referent) pair,
        # which is what `parser/oracle/spec.py`'s flat vocabulary had been
        # writing out by hand (``source_has_subtype`` *and*
        # ``previous_target_has_subtype``, and so on).
        #
        # ``flag`` is the degenerate case — "read a boolean the engine
        # already stamped on this object" — with the attribute name itself a
        # parameter drawn from `SUBJECT_FLAGS`. Eight flat condition keys
        # (``bargained``, ``source_was_cast``, ``cast_via_escape``, …) were
        # that one predicate at eight attributes; a ninth costs a whitelist
        # row rather than a branch. Same shape, and the same security
        # posture, as `continuous.count_selector`'s selector names.
        "flag",  # + ``flag`` (a `SUBJECT_FLAGS` name)
        "power",  # + ``min``/``max`` — the subject's *derived* power
        # "if that player is you" / "…if you control that creature" — the
        # subject (a player, or a player resolved off a firing event) against
        # the ability's own controller.
        "is_you",
        # "~ deals N damage to any target. **If it's a creature**, …" — an
        # "any target" clause can land on a player, so the rider needs to ask
        # which kind of thing the referent turned out to be.
        "is_player",
        "is_ring_bearer",  # RULE 701.52a — the subject is "your" Ring-bearer
        # RULE 702.33b/702.34a Kicker and RULE 107.3c's announced {X}, both
        # read off the subject's own cast-time record. ``min``/``max``, so
        # "was it kicked at all", "was it kicked twice" and "was it *not*
        # kicked" are one row rather than three keys.
        "kicked",  # + ``min``/``max`` (`GameObject.kicker_count`)
        "x_paid",  # + ``min``/``max`` (`GameObject.x_paid`)
        # -- Board/turn facts a *resolving* ability asks (ENG-36). They live
        # here rather than in `effect_conditions` because they need nothing
        # but the state: that module owns only what needs a `GameContext`.
        "no_creatures_on_battlefield",  # RULE 603.4 (Pyrohemia)
        "combats_this_turn",  # + ``min``/``max`` — RULE 603.4, "first combat phase"
        # The pre-daybound Innistrad werewolf day/night check — "no spells
        # were cast last turn" (``max`` 0) and "a player cast 2 or more
        # spells last turn" (``min`` 2) are one quantity at two thresholds.
        "spells_cast_last_turn",  # + ``min``/``max``
        "spells_cast_this_turn",  # + ``min``/``max``, controller-scoped
        "graveyard_count",  # + ``min``/``max`` — raw card count, RULE 702.19
        "ring_tempted",  # + ``min``/``max`` — RULE 701.51b `Player.ring_level`
        "creatures_died_this_turn",  # + ``min``/``max``
        # MEC-84 (Revolt / Disappear): "a permanent left the battlefield under
        # your control this turn" — a controller-scoped turn history, ``min``
        # 1 by default. ``creature_…`` is the RULE 700.4-narrowed sibling.
        "permanent_left_battlefield_this_turn",  # + ``min``/``max``
        "creature_left_battlefield_this_turn",  # + ``min``/``max``
        # "if an opponent lost N or more life this turn" — any one opponent,
        # the same "an opponent" reading as ``opponent_count`` above.
        "opponent_lost_life_this_turn",  # + ``min``/``max``
        "life_lost_this_turn",  # + ``scope`` (you/any), ``min``/``max``
        "life_lost_last_turn",  # + ``scope`` (you/opponents), ``min``/``max``
        "source_dealt_damage_to_opponent_this_turn",
        "source_damage_received_this_turn",  # + ``min``; includes damage before dying
        "opponent_poison_at_least",  # + ``amount`` — any one opponent
        # "if you don't control a Food" — a controller-scoped count of a
        # printed *subtype* word, which neither ``control_count`` (selector
        # vocabulary) nor ``control_named`` (a specific card name) can spell.
        # The "don't" is the ``not`` combinator below, not a second kind.
        "controls_subtype",  # + ``subtype``, ``min``/``max`` (``min`` 1)
        "opponent_cast_color_this_turn",  # + ``colors`` (WUBRG letters)
        "another_spell_cast_this_turn",  # + ``color`` or ``spell_type``
        # -- Combinator (MEC-43 round 2, Conqueror's Flail's "As long as
        # this Equipment is attached to a creature, your opponents can't
        # cast spells during your turn." — two independent gates ANDed in
        # one clause, which no single ``kind`` above can express on its
        # own). + ``conditions`` — a list of these same condition dicts,
        # every one of which must hold.
        "all",
        # Negation (ENG-36). ``{"kind": "not", "condition": {...}}``. Added
        # for the resolution-time vocabulary, where roughly half of the flat
        # keys it replaces were booleans whose ``False`` spelling meant
        # exactly this ("unless its additional cost was paid", "if you chose
        # a creature *other than* ~"). The paired kinds above
        # (``source_tapped``/``source_untapped``, ``your_turn``/
        # ``not_your_turn``, ``is_licid_aura``/``not_licid_aura``) predate it
        # and stay as they are — every shipped spec spells them that way —
        # but a new predicate needs only its positive form now.
        "not",
        # PAR-120: the OR sibling of ``all`` — "you control a desert or there
        # is a desert card in your graveyard" (Desert's Hold and the rest of
        # the Amonkhet Desert-payoff cluster), reached on a static's own "as
        # long as"/an activation condition, not just the resolution-time
        # vocabulary `effect_conditions.py`'s own ``any`` already had (ENG-36)
        # — that module recurses through *this* one for every referent-free
        # sub-condition, so one combinator here now covers both surfaces
        # rather than needing a second. + ``conditions`` — true when *any one*
        # holds.
        "any",
    }
)

#: Attribute names a ``flag`` condition may read off its subject.
#:
#: Every one is a boolean the engine itself stamps at a known choke point,
#: never anything derived from card text; the whitelist is what keeps a
#: condition from turning into an arbitrary attribute read (docs/09). The
#: flat `EffectSpec.condition` key each replaces is named alongside.
SUBJECT_FLAGS: frozenset[str] = frozenset(
    {
        "bargained",  # RULE 601.2b, Beseech the Mirror — was ``bargained``
        # RULE 601.2b's generic optional additional cost, stamped by
        # `GameEngine.cast_spell` — was ``additional_cost_paid``.
        "additional_cost_paid",
        "was_cast",  # RULE 601.2 — was ``source_was_cast``
        "foretold",  # RULE 702.143d — was ``source_was_foretold``
        "cast_via_escape",  # RULE 702.139 — was ``cast_via_escape``
        # RULE 601.3a (Necromancy) — was ``cast_outside_sorcery_speed``.
        "cast_outside_sorcery_speed",
        "cast_during_your_main_phase",  # Addendum (RULE 505.1)
        "renowned",  # RULE 702.111b — was ``source_is_renowned``
        "is_suspected",  # RULE 701.60c — was ``previous_target_is_suspected``
        # RULE 602.2b (an activated ability's sacrifice cost) — "if the sacrificed
        # creature was suspected, draw 2 cards instead" — stamped onto the
        # activating source by `GameEngine`'s cost-payment step, read off *that*
        # object rather than the (now-gone) sacrificed one.
        "sacrificed_cost_was_suspected",
        # RULE 702.194b (PAR-56) — Teamwork's own cast-time record
        # (`GameObject.teamwork_paid`, stamped by `GameEngine.cast_spell`
        # exactly like `bargained`/`additional_cost_paid` above), for
        # resolve-time riders beyond the modal "choose both instead"
        # shape `_modal_override_active` already special-cases.
        "teamwork_paid",
        # RULE 601.2/400.1 (PAR-120) — "if you cast it from your hand" (the
        # "~ enters, if you cast it[ from your hand], …" ETB cluster,
        # distinguishing a cast permanent from one reanimated/cheated in) —
        # `GameObject.was_cast_from_hand`, already stamped by `GameEngine.
        # cast_spell` (`obj.was_cast_from_hand = obj.zone == Zone.HAND`) for
        # an unrelated counter-amount gate; this is its first boolean-
        # condition route.
        "was_cast_from_hand",
    }
)

#: Which object a condition reads, named by its optional ``of`` key.
#:
#: ``source``   — the ability's own source (the default, and what every
#:                condition meant before this key existed).
#: ``attached`` — the permanent the source is *attached to* (RULE 303.4a's
#:                "enchanted permanent" / 301.5c's "equipped creature"): an
#:                Aura's condition about its host rather than about itself.
#: ``affected`` — the permanent a RULE 611 floating static is aimed at, which
#:                only the caller holding the ability can resolve, so it must
#:                be passed in as ``affected``. A condition naming it in a
#:                plain ``active_if`` (where a group static has *many*
#:                affected objects, so the referent is ambiguous) fails closed.
CONDITION_SUBJECTS: frozenset[str] = frozenset({"source", "attached", "affected"})


def _controller(state: "GameState", controller_id: Optional[str]):
    for player in getattr(state, "players", []):
        if player.id == controller_id:
            return player
    return None


def _attached_to_source(state: "GameState", source: Any) -> list[Any]:
    """Every permanent currently attached *to* ``source`` (RULE 301.5/303.4).

    The inverse of `GameObject.attached_to`, which points the other way; an
    Aura/Equipment knows its host, a host doesn't list its attachments.
    """
    instance_id = getattr(source, "instance_id", None)
    if instance_id is None:
        return []
    return [o for o in state.permanents() if getattr(o, "attached_to", None) == instance_id]


def _counter_count(source: Any, kind: Optional[str]) -> int:
    """``source``'s counters of ``kind`` — or its total across kinds when no
    kind is named ("as long as ~ has three or more counters on it")."""
    counters = getattr(source, "counters", None) or {}
    if kind:
        # +1/+1 counters live in their own field, netted by the layer engine.
        if kind == "+1/+1":
            return int(getattr(source, "plus_one_counters", 0) or 0)
        return int(counters.get(kind, 0) or 0)
    total = sum(int(v or 0) for v in counters.values())
    return total + int(getattr(source, "plus_one_counters", 0) or 0)


def _within(n: int, condition: dict[str, Any], default_min: Optional[int] = None) -> bool:
    """``n`` against the condition's optional ``min``/``max`` bounds.

    The counted rows all share this, which is what lets one quantity at two
    thresholds be one ``kind`` — "the Ring has tempted you 3 or more times"
    and "…no more than 3 times" differ only in which bound is set, where the
    flat vocabulary spelled them as two unrelated keys whose relationship
    nothing recorded.
    """
    minimum = condition.get("min", default_min)
    maximum = condition.get("max")
    if minimum is not None and n < int(minimum):
        return False
    if maximum is not None and n > int(maximum):
        return False
    return True


def _subject(
    condition: dict[str, Any],
    state: "GameState",
    source: Any,
    affected: Any,
) -> Any:
    """The object this condition talks about — see `CONDITION_SUBJECTS`.

    ``None`` when the referent doesn't exist (an unattached Aura, a floating
    static with no affected object in hand, an unrecognized ``of``), which
    makes every condition below false: the same fail-closed direction as an
    unknown ``kind``.
    """
    of = condition.get("of") or "source"
    if of not in CONDITION_SUBJECTS:
        return None
    if of == "source":
        return source
    if of == "affected":
        return affected
    host_id = getattr(source, "attached_to", None)
    if host_id is None:
        return None
    for obj in state.permanents():
        if getattr(obj, "instance_id", None) == host_id:
            return obj
    return None


def _events_this_turn_matching(
    state: Any, trigger: dict[str, Any], source: Any, controller_id: str
) -> int:
    """How many events of the current turn a trigger-shaped dict matches (ENG-47).

    The predicate is the binder's own `_trigger_condition` — so "a creature you
    controlled died this turn" means exactly what "whenever a creature you control
    dies" means, including a departed object's last-known values — evaluated against
    the logged events, with ``source`` (or, for a condition with none, the asking
    player) standing in for "you".
    """
    from types import SimpleNamespace

    from .binding.core import _trigger_condition  # local: binding imports this module

    events = trigger["event"] if isinstance(trigger["event"], (list, tuple)) else [trigger["event"]]
    asker = source if source is not None else SimpleNamespace(
        controller_id=controller_id, instance_id=None
    )
    context = SimpleNamespace(state=state)
    predicates = {
        name: _trigger_condition({**trigger, "event": name}, asker) for name in events
    }
    count = 0
    for event in state.events_this_turn():
        name = getattr(event.type, "name", str(event.type))
        if name not in predicates:
            continue
        predicate = predicates[name]
        if predicate is None or predicate(event, context):
            count += 1
    return count


def _selector_arg(selector: Any) -> Any:
    """A count selector as `continuous.count_selector` takes it: a structured dict as
    is, anything else as its string name."""
    return selector if isinstance(selector, dict) else str(selector)


def _selector_label(selector: Any) -> str:
    """A short human label for a selector (named, or a structured dict)."""
    if not isinstance(selector, dict):
        return str(selector)
    filt = ", ".join(str(v) if v is not True else str(k) for k, v in (selector.get("filter") or {}).items())
    return f"{selector.get('zone', 'battlefield')}/{selector.get('of', 'you')}" + (f" [{filt}]" if filt else "")


def condition_holds(
    condition: Optional[dict[str, Any]],
    state: "GameState",
    source: Any = None,
    controller_id: Optional[str] = None,
    affected: Any = None,
) -> bool:
    """Whether ``condition`` holds right now. No condition = always true.

    ``source`` is the ability's own source (the permanent printing "as long
    as ~ …"), ``controller_id`` the player "you" refers to — for a static
    that's the source's controller, which the caller passes rather than
    re-deriving so a control-change (layer 2) that already resolved this pass
    is honoured. ``affected`` is the single permanent a RULE 611 floating
    static is aimed at, needed only by an ``of="affected"`` condition
    (`durations.is_expired` supplies it; nothing else can).
    """
    if not condition:
        return True
    kind = condition.get("kind")
    if kind not in STATIC_CONDITION_KINDS:
        return False  # fail closed — an unmodeled condition never applies

    if kind == "all":
        # Recurses before touching ``subject`` below — a combinator has no
        # subject of its own, only the sub-conditions it ANDs together.
        return all(
            condition_holds(sub, state, source, controller_id, affected)
            for sub in (condition.get("conditions") or [])
        )
    if kind == "any":
        # The OR sibling of ``all`` above — true the moment one sub-condition
        # holds. An empty list is fail-closed (no disjunct to satisfy), the
        # same direction ``all``'s own vacuous-true reading doesn't need to
        # guard against a printed card never producing.
        return any(
            condition_holds(sub, state, source, controller_id, affected)
            for sub in (condition.get("conditions") or [])
        )
    if kind == "not":
        # A missing ``condition`` would make this trivially true, which is
        # the wrong direction for a fail-closed vocabulary — so an empty
        # ``not`` is false, like an unrecognized ``kind``.
        inner = condition.get("condition")
        if not inner or inner.get("kind") not in STATIC_CONDITION_KINDS:
            # An unrecognized inner ``kind`` is *unanswerable*, so neither
            # polarity holds: negating it must not turn "we don't model this"
            # into a gate that always fires.
            return False
        return not condition_holds(inner, state, source, controller_id, affected)

    # Which object the subject-scoped rows below read: the source itself by
    # default, or an attached host / a floating static's affected permanent.
    subject = _subject(condition, state, source, affected)

    if kind == "source_tapped":
        return bool(getattr(subject, "tapped", False))
    if kind == "source_untapped":
        # A subject that has left the battlefield is neither: an absent
        # subject makes every condition false rather than "untapped".
        return subject is not None and not getattr(subject, "tapped", False)
    if kind == "source_monstrous":
        return bool(getattr(subject, "is_monstrous", False))
    if kind == "source_harnessed":  # MEC-79 / RULE 701.64b
        return bool(getattr(subject, "harnessed", False))
    if kind == "is_licid_aura":  # MEC-47 — this Licid is currently an Aura
        return bool(getattr(subject, "is_licid_aura", False))
    if kind == "not_licid_aura":  # MEC-47 — this Licid is still a creature
        return not bool(getattr(subject, "is_licid_aura", False))
    if kind == "source_attacking":
        return bool(getattr(subject, "attacking", False))
    if kind == "source_attacked_this_turn":  # PAR-28 RULE 702.142a
        return bool(getattr(subject, "attacked_this_turn", False))
    if kind == "you_attacked_this_turn":  # PAR-62 / RULE 508.1a (Raid)
        return controller_id in (getattr(state, "players_attacked_this_turn", None) or set())
    if kind == "source_solved":  # PAR-28 RULE 702.169b / 719.3b
        return bool(getattr(subject, "is_solved", False))
    if kind == "your_speed_is_max":  # PAR-28 RULE 702.178a / 702.179e
        player = _controller(state, controller_id)
        return player is not None and int(getattr(player, "speed", 0) or 0) >= 4
    if kind == "your_upkeep":  # PAR-28 RULE 702.57b Forecast
        active = getattr(state, "active_player", None)
        return (
            active is not None
            and controller_id is not None
            and active.id == controller_id
            and getattr(state, "current_step", "") == "upkeep"
        )
    if kind == "source_blocking":
        return getattr(subject, "blocking", None) is not None or bool(
            getattr(subject, "additional_blocking", None)
        )
    if kind == "source_paired":
        return getattr(subject, "paired_with", None) is not None
    if kind == "source_attached":
        return getattr(subject, "attached_to", None) is not None
    if kind in ("source_equipped", "source_enchanted"):
        want_artifact = kind == "source_equipped"
        for attachment in _attached_to_source(state, subject):
            card = getattr(attachment, "card", None)
            is_artifact = bool(getattr(card, "is_artifact", False))
            # "Equipped" means an Equipment is attached; "enchanted", an Aura.
            # Read off the attachment's own card type rather than a subtype
            # string, the same way `continuous._has_card_type` does.
            if is_artifact == want_artifact:
                return True
        return False
    if kind == "source_on_battlefield":
        if subject is None:
            return False
        instance_id = getattr(subject, "instance_id", None)
        return any(o.instance_id == instance_id for o in state.permanents())
    if kind == "source_counters":
        if subject is None:
            return False
        n = _counter_count(subject, condition.get("counter"))
        minimum = condition.get("min")
        maximum = condition.get("max")
        if minimum is not None and n < int(minimum):
            return False
        if maximum is not None and n > int(maximum):
            return False
        return True

    if kind == "flag":
        # See `SUBJECT_FLAGS`. An unlisted name is false rather than an
        # attribute read, so card text can never name its own field.
        name = str(condition.get("flag", ""))
        if subject is None or name not in SUBJECT_FLAGS:
            return False
        return bool(getattr(subject, name, False))
    if kind == "power":
        # Derived power (the layer engine's output), so a pump/anthem that
        # already resolved counts — the same read every other characteristic
        # row here makes.
        if subject is None or not hasattr(subject, "instance_id"):
            return False
        return _within(int(getattr(subject, "power", 0) or 0), condition)
    if kind == "is_you":
        if subject is None or controller_id is None:
            return False
        return getattr(subject, "id", None) == controller_id
    if kind == "is_player":
        # A `Player` has no ``instance_id``; that absence is what the
        # targeting code already uses to tell the two apart.
        return subject is not None and not hasattr(subject, "instance_id")
    if kind == "is_ring_bearer":
        # RULE 701.52a — the controller's chosen bearer, against this
        # subject's own identity.
        player = _controller(state, controller_id)
        bearer_id = getattr(player, "ring_bearer_id", None)
        subject_id = getattr(subject, "instance_id", None)
        return bearer_id is not None and subject_id is not None and bearer_id == subject_id
    if kind == "kicked":  # RULE 702.33b/702.34a
        if subject is None:
            return False
        return _within(int(getattr(subject, "kicker_count", 0) or 0), condition)
    if kind == "x_paid":  # RULE 107.3c
        if subject is None:
            return False
        return _within(int(getattr(subject, "x_paid", 0) or 0), condition)

    if kind in ("is_card_type", "is_color", "is_subtype"):
        # RULE 109.3 characteristics, read through `continuous`'s own matchers
        # so a *derived* type/colour counts (an animated Vehicle is a creature
        # for "as long as enchanted permanent is a creature") rather than only
        # the printed line. Function-scoped: `continuous` imports this module.
        from .continuous import _has_card_type, _has_color, _has_subtype

        if subject is None:
            return False
        if kind == "is_card_type":
            card_type = condition.get("card_type")
            return bool(card_type) and _has_card_type(subject, str(card_type))
        if kind == "is_color":
            color = condition.get("color")
            return bool(color) and _has_color(subject, [str(color)])
        subtype = condition.get("subtype")
        return bool(subtype) and _has_subtype(subject, str(subtype))

    if kind == "is_legendary":
        return subject is not None and bool(getattr(subject, "is_legendary", False))
    if kind == "is_basic":
        card = getattr(subject, "card", None)
        supertypes = str(getattr(card, "type_line", "") or "").split("—")[0].lower().split()
        return "basic" in supertypes
    if kind == "was_dealt_damage_this_turn":
        return subject is not None and int(getattr(subject, "damage_marked", 0) or 0) > 0

    if kind in ("your_turn", "not_your_turn"):
        active = getattr(state, "active_player", None)
        is_yours = active is not None and controller_id is not None and active.id == controller_id
        return is_yours if kind == "your_turn" else not is_yours

    if kind == "is_monarch":
        return controller_id is not None and getattr(state, "monarch_id", None) == controller_id
    if kind == "has_initiative":
        return controller_id is not None and getattr(state, "initiative_id", None) == controller_id
    if kind == "has_city_blessing":
        player = _controller(state, controller_id)
        return bool(player is not None and player.has_city_blessing)
    if kind == "has_enduring_story":
        player = _controller(state, controller_id)
        return bool(player is not None and player.has_enduring_story)

    if kind == "control_count":
        selector = condition.get("selector")
        if not selector or controller_id is None:
            return False
        min_power = condition.get("min_power")
        if min_power is not None and selector == "creatures_you_control":
            # "you control a creature with power N or greater" (Bolt Bend) —
            # a per-object power qualifier on the count, not expressible
            # through `continuous.count_selector`'s flat vocabulary (which
            # only counts, never filters by a derived characteristic), so
            # scanned directly rather than adding one selector name per
            # possible threshold.
            n = sum(
                1
                for o in state.battlefield
                if o.is_creature and o.controller_id == controller_id and (o.power or 0) >= min_power
            )
        else:
            from .continuous import count_selector  # local: continuous imports this module

            # ``source`` matters to two selectors (``exiled_with_source``,
            # ``source_x_paid``) that count something about the ability's own
            # permanent rather than the board; it was omitted here while no
            # static named one, and `effect_conditions` routes the shipped
            # ``count_selector_at_least`` gate through this row (ENG-36).
            n = count_selector(state, controller_id, _selector_arg(selector), source=source)
        minimum = condition.get("min")
        maximum = condition.get("max")
        if minimum is not None and n < int(minimum):
            return False
        if maximum is not None and n > int(maximum):
            return False
        return True
    if kind == "control_legendary_subtype":
        # "as long as you control a legendary Assassin" (Brotherhood Spy and
        # the like) — a live board read, like `control_count` above.
        subtype = str(condition.get("subtype", "")).lower()
        return bool(subtype and controller_id is not None and any(
            o.is_creature and o.controller_id == controller_id
            and "legendary" in str(o.card.type_line).lower()
            and subtype in str(o.card.type_line).lower()
            for o in state.battlefield
        ))
    if kind == "control_permanent_of_each_color":
        # "As long as you control a permanent of each color" (Spirit of
        # Resistance, PAR-78) — unlike `control_count`'s single min/max
        # threshold on one selector, this is five independent booleans
        # (one per WUBRG colour) ANDed together; a devotion-shaped check,
        # not a count.
        if controller_id is None:
            return False
        present = {
            c
            for o in state.battlefield
            if o.controller_id == controller_id
            for c in o.colors
        }
        return {"W", "U", "B", "R", "G"}.issubset(present)
    if kind == "opponent_count":
        # "As long as **an** opponent has N or more cards in their graveyard"
        # (Blackbloom Rogue) — the same `count_selector` vocabulary as
        # ``control_count``, evaluated once per opponent and satisfied by any
        # one of them. "Each opponent" is a different (and so far unprinted in
        # this shape) reading and is deliberately not modeled.
        from .continuous import count_selector  # local: continuous imports this module

        selector = condition.get("selector")
        if not selector or controller_id is None:
            return False
        minimum = condition.get("min")
        maximum = condition.get("max")
        for other in getattr(state, "players", []):
            if other.id == controller_id:
                continue
            n = count_selector(state, other.id, _selector_arg(selector), source=source)
            if minimum is not None and n < int(minimum):
                continue
            if maximum is not None and n > int(maximum):
                continue
            return True
        return False
    if kind == "event_this_turn":
        trigger = condition.get("trigger")
        if not isinstance(trigger, dict) or controller_id is None:
            return False
        n = _events_this_turn_matching(state, trigger, source, controller_id)
        minimum = condition.get("min")
        maximum = condition.get("max")
        if minimum is not None and n < int(minimum):
            return False
        if maximum is not None and n > int(maximum):
            return False
        return True
    if kind == "opponent_has_more":
        # "…if an opponent controls more lands than you" — some one opponent's
        # count of the selector exceeds the ability controller's own (RULE 107.1
        # comparison of two counts of the same structured selector, each read from
        # its own player's point of view).
        from .continuous import count_selector  # local: continuous imports this module

        selector = condition.get("selector")
        if not selector or controller_id is None:
            return False
        mine = count_selector(state, controller_id, _selector_arg(selector), source=source)
        return any(
            count_selector(state, other.id, _selector_arg(selector), source=source) > mine
            for other in getattr(state, "players", [])
            if other.id != controller_id
        )
    if kind == "control_named":
        # "As long as you control a <specific card>" — matched on name, the
        # only stable identity a parsed condition can carry (an instance id
        # can't exist at parse time). Case-folded, since `normalize`
        # lowercases every clause the parser sees.
        name = str(condition.get("name") or "").strip().lower()
        if not name or controller_id is None:
            return False
        return any(
            (getattr(o, "name", "") or "").strip().lower() == name
            and o.controller_id == controller_id
            for o in state.permanents()
        )

    if kind == "no_creatures_on_battlefield":
        # "At the beginning of the end step, if no creatures are on the
        # battlefield, sacrifice ~." (Pyrohemia) — global, unlike
        # ``controls_subtype``'s controller-scoped count.
        return not any(o.is_creature for o in state.battlefield)
    if kind == "combats_this_turn":
        # RULE 603.4's textbook example — "if it's the first combat phase of
        # the turn" is ``max`` 1, and the extra-combat self-loop guard every
        # such grant needs is the same quantity's other bound, rather than a
        # second key.
        return _within(int(getattr(state, "combats_this_turn", 0) or 0), condition)
    if kind == "spells_cast_last_turn":
        # The pre-daybound werewolf day/night check (RULE 603.4), reading
        # `GameState._last_turn_spell_count` — the same field
        # `RulesEngine.apply_day_night_turn_check` (RULE 731.2a/2b) uses.
        # No previous turn (turn 1) means neither bound is answerable, so
        # the condition simply doesn't hold, matching that check's own
        # turn-1 no-op.
        if getattr(state, "_last_turn_player_id", None) is None:
            return False
        return _within(int(getattr(state, "_last_turn_spell_count", 0) or 0), condition)

    if kind == "spells_cast_this_turn":
        if controller_id is None:
            return False
        return _within(
            int((getattr(state, "spells_cast_this_turn", {}) or {}).get(controller_id, 0)),
            condition,
        )

    player = _controller(state, controller_id)
    if player is None:
        return False
    if kind == "life_at_least":
        return int(getattr(player, "life", 0)) >= int(condition.get("amount", 0))
    if kind == "life_at_most":
        return int(getattr(player, "life", 0)) <= int(condition.get("amount", 0))
    if kind == "opponent_life_at_most":
        # "as long as an opponent has 10 or less life" (Bloodghast, PAR-60) —
        # true when *any one* opponent satisfies it, the same "an opponent"
        # semantics as ``opponent_count``.
        threshold = int(condition.get("amount", 0))
        return any(
            int(getattr(p, "life", 0)) <= threshold
            for p in getattr(state, "players", [])
            if p.id not in (None, controller_id)
        )
    if kind == "cards_in_hand_at_least":
        return len(getattr(player, "hand", [])) >= int(condition.get("amount", 0))
    if kind == "cards_in_hand_at_most":
        return len(getattr(player, "hand", [])) <= int(condition.get("amount", 0))
    if kind == "drawn_cards_at_least":
        # "As long as you've drawn two or more cards this turn" (Spinehorn
        # Minotaur-shaped). `GameState.cards_drawn_this_turn` already exists —
        # it is what `continuous`'s ``draw_limit`` permission reads (RULE
        # 616-area "you can't draw more than one card each turn") — and is
        # reset per turn by the same bookkeeping, so this is a read, not a new
        # counter.
        drawn = getattr(state, "cards_drawn_this_turn", None) or {}
        amount = int(condition.get("amount", 0))
        if condition.get("scope") == "opponents":
            return any(
                int(drawn.get(p.id, 0) or 0) >= amount
                for p in state.living_players() if p.id != controller_id
            )
        return int(drawn.get(controller_id, 0) or 0) >= amount
    if kind == "mana_color_spent_to_cast_at_least":
        color = str(condition.get("color", "")).upper()
        return int((getattr(source, "mana_by_color_spent_to_cast", None) or {}).get(color, 0)) >= int(condition.get("amount", 1))
    if kind == "treasure_mana_spent_to_cast":
        return int(getattr(source, "mana_spent_to_cast_treasure", 0) or 0) > 0
    if kind == "treasure_mana_spent_to_activate":
        return int(getattr(source, "mana_spent_to_activate_treasure", 0) or 0) > 0
    if kind == "cast_instant_or_sorcery_this_turn":
        cast = getattr(state, "cast_instant_or_sorcery_this_turn", None) or {}
        return bool(cast.get(controller_id, False))
    if kind == "cast_noncreature_spell_this_turn":
        cast = getattr(state, "noncreature_spells_cast_this_turn", None) or {}
        return int(cast.get(controller_id, 0) or 0) > 0
    if kind == "gained_life_this_turn":
        # "if you gained life this turn" (Eccentric Pestfinder / Witch of the
        # Moors / Mortality Spear, PAR-60) — `GameState.life_gained_this_turn`
        # is bumped at `RulesEngine.gain_life`'s single choke point and reset
        # per turn, so this is a read, not a new counter. Optional ``amount``
        # (default 1) for the rare "gained N or more life this turn" phrasing.
        gained = getattr(state, "life_gained_this_turn", None) or {}
        return int(gained.get(controller_id, 0) or 0) >= int(condition.get("amount", 1) or 1)
    if kind == "descended_this_turn":
        return controller_id in (getattr(state, "permanent_card_to_graveyard_this_turn", None) or set())
    if kind == "card_left_graveyard_this_turn":
        return controller_id in getattr(state, "cards_left_graveyard_this_turn", set())
    if kind == "graveyard_card_type_count_at_least":
        # "if there are 3 or more artifact and/or creature cards in your
        # graveyard" (Lorehold Archivist, PAR-60). + ``types`` (a list of
        # lowercase card-type words, ORed per card) and ``amount``.
        want = {str(t).lower() for t in (condition.get("types") or [])}
        need = int(condition.get("amount", 1) or 1)
        hits = sum(
            1 for o in getattr(player, "graveyard", [])
            if want & {w for w in getattr(o, "type_words", set()) if w != "permanent"}
        )
        return hits >= need
    if kind == "control_no_creatures_with_keyword":
        # "if you control no creatures with decayed" (Jadar, Ghoulcaller of
        # Nephalia, PAR-60) — a keyword-scoped control-count, unlike
        # ``control_count``'s subtype selectors. + ``keyword`` (a lowercase
        # keyword slug checked against each creature's granted + intrinsic
        # keyword union).
        word = str(condition.get("keyword", "")).lower()
        try:
            from .continuous import _obj_keywords
        except Exception:  # pragma: no cover - defensive
            _obj_keywords = None
        for o in getattr(state, "battlefield", []):
            if not (o.is_creature and o.controller_id == controller_id):
                continue
            kws = _obj_keywords(o) if _obj_keywords else (
                set(getattr(o, "granted_keywords", set()))
                | set(getattr(o, "intrinsic_keywords", set()))
            )
            if word in {str(k).lower() for k in kws}:
                return False
        return True
    if kind == "any_player_cards_in_hand_at_most":
        # "if a player has one or fewer cards in hand" (Naktamun Lorespinner,
        # PAR-60) — "a player" = any player, including you. + ``amount``.
        n = int(condition.get("amount", 0))
        return any(
            len(getattr(p, "hand", [])) <= n for p in getattr(state, "players", [])
        )
    if kind == "active_player_cards_in_hand_at_most":
        active = getattr(state, "active_player", None)
        if active is None:
            return False
        return len(getattr(active, "hand", [])) <= int(condition.get("amount", 0))
    if kind == "opponent_controls_more_lands":
        from .continuous import count_selector
        mine = count_selector(state, controller_id, "lands_you_control")
        return any(
            count_selector(state, p.id, "lands_you_control") > mine
            for p in getattr(state, "players", [])
            if p.id not in (None, controller_id)
        )
    if kind == "you_dealt_damage_this_turn_at_least":
        # PAR-32 (Dragon Cultist): "if a source you controlled dealt N or
        # more damage this turn" — `GameState.damage_dealt_by_this_turn`,
        # keyed by the dealing source's controller.
        by = getattr(state, "damage_dealt_by_this_turn", None) or {}
        return int(by.get(controller_id, 0) or 0) >= int(condition.get("amount", 1) or 1)
    if kind == "creature_card_to_graveyard_this_turn":
        # PAR-32 (Cloakwood Hermit): "if a creature card was put into your
        # graveyard from anywhere this turn" — `GameState.creature_card_to_
        # graveyard_this_turn`, a set of owner ids.
        seen = getattr(state, "creature_card_to_graveyard_this_turn", None) or set()
        return controller_id in seen
    if kind == "you_placed_counter_on_creature_this_turn":
        # Lasting Tarfire: "if you put a counter on a creature this turn" —
        # `GameState.counter_placed_on_creature_this_turn`, a set of the
        # COUNTER event's causer (``source_controller_id``) ids.
        seen = getattr(state, "counter_placed_on_creature_this_turn", None) or set()
        return controller_id in seen
    if kind == "first_subtype_spell_this_turn":
        # MEC-60 (Acolyte of Bahamut): "The first Dragon spell you cast each
        # turn costs {2} less to cast." True until `controller_id` has cast
        # a spell carrying this subtype this turn — checked at cost-
        # computation time, before the spell being priced is itself
        # recorded (`RulesEngine._track_spell_cast` only tallies a cast
        # *after* it commits), so the spell that actually earns the
        # discount is always "the first" by construction.
        seen = getattr(state, "creature_type_spells_cast_this_turn", None) or {}
        subtype = str(condition.get("subtype", "")).lower()
        return subtype not in seen.get(controller_id, set())
    if kind == "subtype_in_graveyard":
        # PAR-30: "as long as there's a `<subtype>` card in your graveyard."
        # A live scan of the controller's graveyard for a card whose type
        # line carries the named word (main type or subtype) — the same
        # convention `effects.ConditionalEffect`'s `graveyard_has_type`
        # branch uses, just as an `active_if` static gate.
        word = str(condition.get("subtype", "")).lower()
        if not word:
            return False
        minimum = int(condition.get("min", 1) or 1)
        hits = sum(
            1 for obj in getattr(player, "graveyard", [])
            if word in obj.card.type_line.lower()
        )
        return hits >= minimum
    if kind == "distinct_mana_values_in_graveyard_at_least":
        # Sewer Crocodile: cards with the same mana value count only once.
        minimum = int(condition.get("min", 1) or 1)
        return len({
            int(getattr(obj.card, "converted_mana_cost", 0) or 0)
            for obj in getattr(player, "graveyard", [])
        }) >= minimum
    if kind == "another_subtype_entered_this_turn":
        # MEC-46 (Galadriel): a permanent other than the source, controlled
        # by "you", carrying the named type word, that entered this turn.
        word = str(condition.get("subtype", "")).lower()
        if not word:
            return False
        src_id = getattr(source, "instance_id", None)
        turn = getattr(state.internal_turn, "number", None)
        for obj in state.permanents():
            if obj.instance_id == src_id:
                continue
            if getattr(obj, "controller_id", None) != controller_id:
                continue
            if getattr(obj, "turn_entered", None) != turn:
                continue
            if word in obj.card.type_line.lower():
                return True
        return False
    if kind == "card_types_in_graveyard_at_least":
        # RULE 702.137's "Delirium" — count *distinct card types* (RULE
        # 205.2a) among cards in your graveyard (Dragon's Rage Channeler/
        # Winter, Misanthropic Guide-shaped). `continuous.card_types_of`
        # drops what `GameObject.type_words` carries that isn't a card type:
        # the synthetic "permanent" marker and every supertype — a Legendary
        # Sorcery used to count as two types here.
        from .continuous import card_types_of  # local: continuous imports this module

        types: set[str] = set()
        for obj in getattr(player, "graveyard", []):
            types |= card_types_of(obj)
        return len(types) >= int(condition.get("amount", 0))
    if kind == "graveyard_count":
        # RULE 702.19 Threshold's raw card count, unlike
        # ``card_types_in_graveyard_at_least`` (distinct types) or
        # ``graveyard_card_type_count_at_least`` (a type filter).
        return _within(len(getattr(player, "graveyard", []) or []), condition)
    if kind == "ring_tempted":
        # RULE 701.51b — `Player.ring_level`, capped at 4.
        return _within(int(getattr(player, "ring_level", 0) or 0), condition)
    if kind == "creatures_died_this_turn":
        # `GameState.creatures_died_this_turn`, tallied at
        # `RulesEngine._move_to_graveyard`'s own DIES handling.
        died = getattr(state, "creatures_died_this_turn", None) or {}
        return _within(int(died.get(controller_id, 0) or 0), condition)
    if kind == "permanent_left_battlefield_this_turn":  # MEC-84 — Revolt
        left = getattr(state, "permanents_left_battlefield_this_turn", None) or {}
        return _within(int(left.get(controller_id, 0) or 0), condition, default_min=1)
    if kind == "creature_left_battlefield_this_turn":  # MEC-84
        left = getattr(state, "creatures_left_battlefield_this_turn", None) or {}
        return _within(int(left.get(controller_id, 0) or 0), condition, default_min=1)
    if kind == "opponent_lost_life_this_turn":
        # True when *any one* opponent is inside the bounds — the same "an
        # opponent" reading as ``opponent_count``/``opponent_life_at_most``.
        lost = getattr(state, "life_lost_this_turn", None) or {}
        return any(
            _within(int(lost.get(p.id, 0) or 0), condition)
            for p in state.living_players()
            if p.id != controller_id
        )
    if kind == "life_lost_this_turn":
        lost = getattr(state, "life_lost_this_turn", None) or {}
        if condition.get("scope") == "you":
            return _within(int(lost.get(controller_id, 0) or 0), condition)
        if condition.get("scope") == "any":
            return any(_within(int(lost.get(p.id, 0) or 0), condition)
                       for p in state.living_players())
        return False
    if kind == "life_lost_last_turn":
        lost: dict[str, int] = {}
        for event in state.events_last_turn():
            if event.type == "LIFE_LOST":
                pid = event.get("player_id")
                if pid is not None:
                    lost[pid] = lost.get(pid, 0) + int(event.get("amount") or 0)
        if condition.get("scope") == "you":
            return _within(lost.get(controller_id, 0), condition, default_min=1)
        if condition.get("scope") == "opponents":
            return any(_within(lost.get(p.id, 0), condition, default_min=1)
                       for p in state.living_players() if p.id != controller_id)
        return False
    if kind == "source_dealt_damage_to_opponent_this_turn":
        source_id = getattr(source, "instance_id", None)
        return source_id is not None and any(
            event.type == "DAMAGE" and event.get("source_id") == source_id
            and event.get("is_player") and event.get("target_id") != event.get("source_controller_id")
            and int(event.get("amount") or 0) > 0
            for event in state.events_this_turn()
        )
    if kind == "source_damage_received_this_turn":
        source_id = getattr(source, "instance_id", None)
        if source_id is None:
            return False
        total = sum(int(event.get("amount") or 0) for event in state.events_this_turn()
                    if event.type == "DAMAGE" and not event.get("is_player")
                    and event.get("target_id") == source_id)
        return _within(total, condition)
    if kind == "opponent_poison_at_least":
        amount = int(condition.get("amount", 0))
        return any(int(getattr(p, "poison", 0) or 0) >= amount
                   for p in state.living_players() if p.id != controller_id)
    if kind == "controls_subtype":
        # A live battlefield scan for the controller's own permanents whose
        # printed *subtype* portion carries the word — the same word-list
        # convention `segmenter._SACRIFICE_TYPE_TRIGGER_RE`/
        # `_NAMED_TOKEN_WORDS` already trust. ``min`` defaults to 1, since
        # "you control a Food" is the only phrasing that reaches here
        # without an explicit bound.
        word = str(condition.get("subtype", "")).lower()
        if not word:
            return False
        n = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id
            and word in o.card.type_line.partition("—")[2].strip().lower().split()
        )
        return _within(n, condition, default_min=1)
    if kind == "opponent_cast_color_this_turn":
        # "…if an opponent has cast a blue or black spell this turn."
        # (Veil of Summer) — any opponent's `GameState.
        # spell_colors_cast_this_turn` intersecting ``colors``.
        wanted = {str(c).upper() for c in (condition.get("colors") or [])}
        cast = getattr(state, "spell_colors_cast_this_turn", None) or {}
        return any(colors & wanted for pid, colors in cast.items() if pid != controller_id)
    if kind == "another_spell_cast_this_turn":
        color = condition.get("color")
        spell_type = condition.get("spell_type")
        if color and not spell_type:
            counts = getattr(state, "spell_color_cast_counts_this_turn", None) or {}
            return int((counts.get(controller_id, {}) or {}).get(str(color).upper(), 0)) >= 2
        if spell_type and not color:
            counts = getattr(state, "spell_type_cast_counts_this_turn", None) or {}
            return int((counts.get(controller_id, {}) or {}).get(str(spell_type).lower(), 0)) >= 2
        return False
    return False


def condition_from_legacy_params(params: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The pre-existing per-card gate params → this vocabulary, or ``None``.

    `continuous.group_selector_objects` grew three ad-hoc conditional gates
    before this module existed, and every shipped `AbilitySpec` still spells
    them that way. Rather than rewrite those specs (and the tests pinning
    them), they are translated here so there is exactly one evaluator:

    * ``active_player_only``  → ``your_turn``
    * ``min_level``/``max_level`` (+ ``level_counter``) → ``source_counters``
    * ``min_count_selector``/``min_count``  → ``control_count``

    Returns ``None`` when the params carry no legacy gate at all.
    """
    if params.get("active_player_only"):
        return {"kind": "your_turn"}
    min_level = params.get("min_level")
    max_level = params.get("max_level")
    if min_level is not None or max_level is not None:
        condition: dict[str, Any] = {
            "kind": "source_counters",
            "counter": params.get("level_counter") or "level",
        }
        if min_level is not None:
            condition["min"] = min_level
        if max_level is not None:
            condition["max"] = max_level
        return condition
    selector = params.get("min_count_selector")
    minimum = params.get("min_count")
    if selector is not None and minimum is not None:
        return {"kind": "control_count", "selector": selector, "min": minimum}
    return None


def describe(condition: Optional[dict[str, Any]]) -> str:
    """A terse German label for the board's static-effect trace panel.

    Matches `continuous._describe_combat_restriction`'s register: a few words
    naming the gate, not a sentence.
    """
    if not condition:
        return ""
    kind = str(condition.get("kind", ""))
    if kind == "all":
        parts = [describe(sub).removeprefix("solange ") for sub in (condition.get("conditions") or [])]
        return "solange " + " und ".join(p for p in parts if p) if parts else "bedingt"
    if kind == "any":
        parts = [describe(sub).removeprefix("solange ") for sub in (condition.get("conditions") or [])]
        return "solange " + " oder ".join(p for p in parts if p) if parts else "bedingt"
    if kind == "not":
        inner = describe(condition.get("condition")).removeprefix("solange ")
        return f"solange nicht {inner}" if inner else "bedingt"
    # The subject-scoped rows read "solange <X>"; with ``of`` naming something
    # other than the source, say which permanent is meant.
    of = condition.get("of") or "source"
    subject = {"attached": "verzaubertes/ausgerüstetes Objekt", "affected": "betroffen"}.get(of, "")
    prefix = f"solange {subject} " if subject else "solange "
    labels = {
        "source_tapped": "getappt",
        "source_untapped": "ungetappt",
        "source_monstrous": "monströs",
        "source_harnessed": "gezähmt",
        "source_attacking": "angreifend",
        "source_blocking": "blockend",
        "source_paired": "verbündet",
        "source_attached": "angelegt",
        "source_equipped": "ausgerüstet",
        "source_enchanted": "verzaubert",
        "source_attacked_this_turn": "hat diesen Zug angegriffen",
        "you_attacked_this_turn": "du hast diesen Zug angegriffen",
        "source_solved": "solange gelöst",
    }
    if kind == "your_speed_is_max":
        return "solange Höchsttempo (Speed 4)"
    if kind in labels:
        return prefix + labels[kind]
    if kind == "your_turn":
        return "nur in deinem Zug"
    if kind == "not_your_turn":
        return "nur außerhalb deines Zuges"
    if kind == "is_monarch":
        return "solange Monarch"
    if kind == "has_initiative":
        return "solange Initiative"
    if kind == "has_city_blessing":
        return "solange Segen der Stadt"
    if kind == "has_enduring_story":
        return "solange andauernde Geschichte"
    if kind == "source_on_battlefield":
        return prefix + "im Spiel"
    if kind == "is_card_type":
        return prefix + f"ein(e) {condition.get('card_type', '')}"
    if kind == "is_color":
        return prefix + f"Farbe {condition.get('color', '')}"
    if kind == "is_subtype":
        return prefix + f"vom Typ {condition.get('subtype', '')}"
    if kind == "source_counters":
        return prefix + f"≥{condition.get('min', 1)} {condition.get('counter', 'Marken')}"
    if kind == "control_count":
        return f"solange ≥{condition.get('min', 1)} {_selector_label(condition.get('selector', ''))}"
    if kind == "opponent_count":
        return f"solange Gegner ≥{condition.get('min', 1)} {_selector_label(condition.get('selector', ''))}"
    if kind == "opponent_has_more":
        return f"solange ein Gegner mehr hat als du: {_selector_label(condition.get('selector', ''))}"
    if kind == "event_this_turn":
        return f"falls diesen Zug {condition.get('trigger', {}).get('event', '')} eingetreten ist"
    if kind == "control_named":
        return f"solange du {condition.get('name', '')} kontrollierst"
    if kind == "drawn_cards_at_least":
        return f"solange ≥{condition.get('amount', 0)} Karten gezogen"
    if kind == "card_types_in_graveyard_at_least":
        return f"Delirium (≥{condition.get('amount', 0)} Kartentypen im Friedhof)"
    if kind == "subtype_in_graveyard":
        return f"solange ≥{condition.get('min', 1)} {condition.get('subtype', '')}-Karte im Friedhof"
    if kind == "another_subtype_entered_this_turn":
        return f"falls diesen Zug ein weiterer {condition.get('subtype', '')} ins Spiel kam"
    if kind == "permanent_left_battlefield_this_turn":
        return "Revolt (ein bleibende Karte hat diesen Zug unter deiner Kontrolle das Schlachtfeld verlassen)"
    if kind == "creature_left_battlefield_this_turn":
        return "falls diesen Zug eine Kreatur unter deiner Kontrolle das Schlachtfeld verlassen hat"
    if kind.startswith("life_"):
        return f"solange Leben {'≥' if kind.endswith('least') else '≤'}{condition.get('amount', 0)}"
    if kind.startswith("cards_in_hand_"):
        return f"solange Handkarten {'≥' if kind.endswith('least') else '≤'}{condition.get('amount', 0)}"
    return "bedingt"
