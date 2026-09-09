"""Blight Curse Commander deck catalogue entries.

Cards in this module have card-specific casting/amount semantics that the
fail-closed oracle parser must not guess.  Each factory remains pure so a
second object of the card receives fresh specs.
"""

from __future__ import annotations

from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register


def _cathartic_reunion() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, discard two cards.
    Draw three cards."""
    return [
        AbilitySpec(
            "spell_effect", [EffectSpec("draw", {"count": 3})],
            additional_cost={"discard": 2},
        )
    ]


register("Cathartic Reunion", _cathartic_reunion)


def _chain_reaction() -> list[AbilitySpec]:
    """Chain Reaction deals X damage to each creature, where X is the
    number of creatures on the battlefield."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": 0, "selector": "each_creature",
                "amount_from_count_selector": "all_creatures",
            })],
        )
    ]


register("Chain Reaction", _chain_reaction)


def _necroskitter() -> list[AbilitySpec]:
    """Wither (This deals damage to creatures in the form of -1/-1 counters.)
    Whenever a creature an opponent controls with a -1/-1 counter on it
    dies, you may return that card to the battlefield under your control.

    Wither folds in from the RULE 702 keyword catalogue. The dies trigger
    rides `AbilitySpec.counter_death_return` (`RulesEngine._collect_counter_
    death_return_triggers`) — the Marchesa primitive, with ``opponent`` (the
    dying creature is an opponent's), ``immediate`` (no "next end step"
    delay), ``optional`` ("you may").
    """
    return [
        AbilitySpec(
            "static", [],
            counter_death_return={
                "counter_kind": "-1/-1", "opponent": True,
                "immediate": True, "optional": True,
            },
        )
    ]


register("Necroskitter", _necroskitter)


def _the_reaper_king_no_more() -> list[AbilitySpec]:
    """When The Reaper enters, put a -1/-1 counter on each of up to two
    target creatures.
    Whenever a creature an opponent controls with a -1/-1 counter on it
    dies, you may put that card onto the battlefield under your control.
    Do this only once each turn.

    Registered wholesale (so the parser is skipped), so both clauses are
    authored: the ETB as an ordinary ``add_counters`` "each of up to two
    target creatures" triggered ability, the dies trigger as
    `counter_death_return` with ``once_per_turn`` (RULE 603.2) on top of
    Necroskitter's opponent/immediate/optional shape.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "-1/-1", "target_kind": "creature",
                "target_count": 2, "optional": True,
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static", [],
            counter_death_return={
                "counter_kind": "-1/-1", "opponent": True, "immediate": True,
                "optional": True, "once_per_turn": True,
            },
        ),
    ]


register("The Reaper, King No More", _the_reaper_king_no_more)


def _hapatra_vizier_of_poisons() -> list[AbilitySpec]:
    """Whenever Hapatra deals combat damage to a player, you may put a
    -1/-1 counter on target creature.
    Whenever you put one or more -1/-1 counters on a creature, create a
    1/1 green Snake creature token with deathtouch.

    Registered wholesale, so both clauses are authored. The second is the
    Flourishing Defenses `EventType.COUNTER` shape (``kind``/
    ``recipient_is_creature``) plus the new causer-scoped ``by_you`` filter
    key (`effect_binder` — "whenever **you** put …", `COUNTER`'s
    ``source_controller_id``). "One or more" is the event itself: the
    engine fires one `COUNTER` per `add_counters` call regardless of amount.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "-1/-1", "target_kind": "creature"})],
            trigger={"event": "DAMAGE", "filter": {"combat": True, "is_player": True}},
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Snake"], "keywords": ["deathtouch"], "token_name": "Snake",
            })],
            trigger={
                "event": "COUNTER",
                "filter": {"kind": "-1/-1", "recipient_is_creature": True, "by_you": True},
            },
        ),
    ]


register("Hapatra, Vizier of Poisons", _hapatra_vizier_of_poisons)


def _auntie_ool_cursewretch() -> list[AbilitySpec]:
    """Ward—Blight 2. (To blight 2, a player puts two -1/-1 counters on a
    creature they control.)
    Whenever one or more -1/-1 counters are put on a creature, draw a card
    if you control that creature. If you don't control it, its controller
    loses 1 life.

    Ward—Blight 2 folds in from the RULE 702 keyword catalogue for free
    (`parse_keywords` → ``{"name": "ward", "cost": "Blight 2"}``, and
    `game/costs.parse_activation_cost` already reads "Blight 2" → RULE
    701.68). Only the trigger needs authoring: the Flourishing Defenses
    `EventType.COUNTER` shape (unscoped — any creature, any causer) with a
    two-way `ConditionalEffect` branch on the firing event's
    ``recipient_controller_id`` (`counter_recipient_is_you`): draw if it's
    yours, else that creature's controller loses 1 life
    (`LoseLifeEffect` ``selector="counter_recipient_controller"``).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}, condition={"counter_recipient_is_you": True}),
                EffectSpec(
                    "lose_life",
                    {"amount": 1, "selector": "counter_recipient_controller"},
                    condition={"counter_recipient_is_you": False},
                ),
            ],
            trigger={
                "event": "COUNTER",
                "filter": {"kind": "-1/-1", "recipient_is_creature": True},
            },
        ),
    ]


register("Auntie Ool, Cursewretch", _auntie_ool_cursewretch)


def _wickersmiths_tools() -> list[AbilitySpec]:
    """Whenever one or more -1/-1 counters are put on a creature, put a
    charge counter on this artifact.
    {T}: Add one mana of any color.
    {5}, {T}, Sacrifice this artifact: Create X tapped 2/2 colorless
    Scarecrow artifact creature tokens, where X is the number of charge
    counters on this artifact.

    The mana ability folds in from `mana_abilities_for` (independent of
    catalogue registration). Authored here: the Flourishing Defenses
    `EventType.COUNTER` charge-counter trigger (unscoped), and the
    sacrifice ability whose token count is ``count_selector=
    "charge_counters_on_source"`` (`continuous.count_selector`, resolved
    once as the ability resolves — the card's only ruling).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "charge"})],
            trigger={
                "event": "COUNTER",
                "filter": {"kind": "-1/-1", "recipient_is_creature": True},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "power": 2, "toughness": 2, "colors": [], "subtypes": ["Scarecrow"],
                "token_name": "Scarecrow", "is_artifact": True, "tapped": True,
                "count_selector": "charge_counters_on_source",
            })],
            cost={"text": "{5}, {T}, Sacrifice ~"},
        ),
    ]


register("Wickersmith's Tools", _wickersmiths_tools)


def _massacre_girl_known_killer() -> list[AbilitySpec]:
    """Menace
    Creatures you control have wither. (They deal damage to creatures in
    the form of -1/-1 counters.)
    Whenever a creature an opponent controls dies, if its toughness was
    less than 1, draw a card.

    Menace folds in from the RULE 702 catalogue. Authored: the wither
    anthem (ordinary layer-6 ``grant_keyword``), and the dies trigger —
    the C3a "an opponent controls" group subject with a new
    `ConditionalEffect` ``dying_creature_toughness_below`` gate on the DIES
    event's snapshotted last-known toughness (RULE 603.6a).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control", "keywords": ["wither"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature",
                              "controller": "not_you", "other": False},
                # RULE 603.4 intervening-if on the dying creature's own
                # last-known toughness (checked at trigger time).
                "dying_toughness_below": 1,
            },
        ),
    ]


register("Massacre Girl, Known Killer", _massacre_girl_known_killer)


def _dusk_urchins() -> list[AbilitySpec]:
    """Whenever this creature attacks or blocks, put a -1/-1 counter on it.
    When this creature dies, draw a card for each -1/-1 counter on it.

    Authored: the attack/block self-counter trigger (ordinary
    ``add_counters`` on the source), and the dies trigger whose draw count
    is ``count_from_trigger_event_counter="-1/-1"`` — read off the firing
    DIES event's snapshotted ``counters`` dict (RULE 400.7).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "-1/-1"})],
            trigger={"event": "ATTACKS", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "-1/-1"})],
            trigger={"event": "BLOCKS", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1, "count_from_trigger_event_counter": "-1/-1"})],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
        ),
    ]


register("Dusk Urchins", _dusk_urchins)


def _midnight_banshee() -> list[AbilitySpec]:
    """Wither
    At the beginning of your upkeep, put a -1/-1 counter on each nonblack
    creature.

    Wither folds in from the RULE 702 catalogue. Authored: the upkeep
    trigger — an ``add_counters`` mass selector (``"each_creature"``)
    narrowed by ``creature_filter={"without_color": "B"}`` (RULE 105 —
    "nonblack"), the same `matches_object_filter` key the single-target
    branch already honours.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "-1/-1", "selector": "each_creature",
                "creature_filter": {"without_color": "B"},
            })],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Midnight Banshee", _midnight_banshee)


def _blowfly_infestation() -> list[AbilitySpec]:
    """Whenever a creature dies, if it had a -1/-1 counter on it, put a
    -1/-1 counter on target creature.

    The C3a "a creature dies" group subject (any controller) with a new
    `ConditionalEffect` ``dying_creature_had_counter`` gate on the DIES
    event's snapshotted ``counters`` (RULE 400.7), then an ordinary
    targeted ``add_counters``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "-1/-1", "target_kind": "creature",
            })],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature",
                              "controller": "any", "other": False},
                # RULE 603.4 intervening-if — only triggers (and only then
                # prompts for a target) if the dead creature had a -1/-1
                # counter on it.
                "dying_had_counter": "-1/-1",
            },
        ),
    ]


register("Blowfly Infestation", _blowfly_infestation)


def _painful_truths() -> list[AbilitySpec]:
    """Converge — You draw X cards and lose X life, where X is the number
    of colors of mana spent to cast this spell.

    RULE 702.108a Converge: X is ``len(GameObject.colors_spent_to_cast)``,
    the WUBRG frozenset the mana-payment solver stamps on the spell at
    cast. Both ``draw`` and ``lose_life`` read it via the new
    ``amount_from_count_selector="converge"`` (`continuous.count_selector`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": 0, "amount_from_count_selector": "converge"}),
                EffectSpec("lose_life", {"amount": 0, "amount_from_count_selector": "converge"}),
            ],
        ),
    ]


register("Painful Truths", _painful_truths)


def _grave_venerations() -> list[AbilitySpec]:
    """When this enchantment enters, you become the monarch.
    At the beginning of your end step, if you're the monarch, return up to
    one target creature card from your graveyard to your hand.
    Whenever a creature you control dies, each opponent loses 1 life and
    you gain 1 life.

    Registered wholesale, so all three clauses are authored. The end-step
    clause carries a trigger-level RULE 603.4 intervening-if
    (``active_if={"kind": "is_monarch"}``) — the same `static_conditions`
    vocabulary a static's own `active_if` uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_monarch", {})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "hand", "optional": True,
            })],
            trigger={
                "event": "STEP_BEGIN", "filter": {"step": "end"}, "phase_relation": "you",
                "active_if": {"kind": "is_monarch"},
            },
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"}),
                EffectSpec("gain_life", {"amount": 1}),
            ],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature",
                              "controller": "you", "other": False},
            },
        ),
    ]


register("Grave Venerations", _grave_venerations)


def _ifnir_deadlands() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}, Pay 1 life: Add {B}.
    {2}{B}{B}, {T}, Sacrifice a Desert: Put two -1/-1 counters on target
    creature an opponent controls. Activate only as a sorcery.

    Both mana abilities fold in from `mana_abilities_for` (independent of
    registration). Authored: the sorcery-speed sacrifice ability — the
    cost's ``Sacrifice a Desert`` subtype filter is already understood by
    `game/costs.parse_activation_cost`; the effect is a plain targeted
    ``add_counters`` (``creature_you_dont_control``, RULE 115).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {
                "count": 2, "kind": "-1/-1", "target_kind": "creature_you_dont_control",
            })],
            cost={"text": "{2}{B}{B}, {T}, Sacrifice a Desert", "sorcery_speed_only": True},
        ),
    ]


register("Ifnir Deadlands", _ifnir_deadlands)


def _archfiend_of_ifnir() -> list[AbilitySpec]:
    """Flying
    Whenever you cycle or discard another card, put a -1/-1 counter on
    each creature your opponents control.
    Cycling {2}

    Flying + Cycling fold in from the RULE 702 catalogue. The trigger is
    two distinct events — `EventType.CYCLED` (cycling's discard is a
    *cost*, not a "discard" game action) and `EventType.DISCARD_CARD` — so
    it's authored as two triggered abilities, each with ``other=True``
    (RULE 109.5 "another card"). The effect is a mass ``add_counters``
    with ``selector="each_creature_opponents_control"``.
    """
    _effect = [EffectSpec("add_counters", {
        "count": 1, "kind": "-1/-1", "selector": "each_creature_opponents_control",
    })]
    return [
        AbilitySpec(
            "triggered", list(_effect),
            trigger={"event": "CYCLED", "condition": {"subject": "you"}, "other": True},
        ),
        AbilitySpec(
            "triggered", list(_effect),
            trigger={"event": "DISCARD_CARD", "condition": {"subject": "you"}, "other": True},
        ),
    ]


register("Archfiend of Ifnir", _archfiend_of_ifnir)


def _nesting_grounds() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {1}, {T}: Move a counter from target permanent you control onto a
    second target permanent. Activate only as a sorcery.

    The mana ability folds in from `mana_abilities_for`. Authored: the
    sorcery-speed move-a-counter ability (new `MoveCountersEffect` —
    ``permanent_you_control`` source + a distinct second ``permanent``
    target, RULE 122.3).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("move_counters", {})],
            cost={"text": "{1}, {T}", "sorcery_speed_only": True},
        ),
    ]


register("Nesting Grounds", _nesting_grounds)


def _kulrath_knight() -> list[AbilitySpec]:
    """Flying
    Wither (This deals damage to creatures in the form of -1/-1 counters.)
    Creatures your opponents control with counters on them can't attack
    or block.

    Flying + Wither fold in from the RULE 702 keyword catalogue. Authored:
    the static (RULE 613.7f layer-6 grant) that hands ``cant_attack`` /
    ``cant_block`` — the synthetic flag keywords `game/combat.py` already
    reads at declare-attackers / declare-blockers — to the new
    ``creatures_opponents_control_with_a_counter`` affected set (any
    counter kind, RULE 122.1).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_opponents_control_with_a_counter",
                "keywords": ["cant_attack", "cant_block"],
            })],
        ),
    ]


register("Kulrath Knight", _kulrath_knight)


def _tree_of_perdition() -> list[AbilitySpec]:
    """Defender
    {T}: Exchange target opponent's life total with this creature's
    toughness.

    Defender folds in from the RULE 702 keyword catalogue. Authored: the
    activated ability — new bespoke `ExchangeLifeTotalWithToughnessEffect`
    ("exchange_life_total_with_toughness"): the opponent's life becomes ~'s
    former toughness (via life gain/loss, ruling 1) and ~'s base toughness
    is set to the opponent's former life by a permanent toughness-only
    layer-7b `pt_set` (ruling 2).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_life_total_with_toughness", {})],
            cost={"text": "{T}"},
        ),
    ]


register("Tree of Perdition", _tree_of_perdition)


def _lasting_tarfire() -> list[AbilitySpec]:
    """At the beginning of each end step, if you put a counter on a creature
    this turn, this enchantment deals 2 damage to each opponent.

    Authored: one triggered ability on *each* end step (no
    ``phase_relation``), with a trigger-level RULE 603.4 intervening-if
    (``active_if={"kind": "you_placed_counter_on_creature_this_turn"}``) that
    reads the new `GameState.counter_placed_on_creature_this_turn` causer
    set, populated in `RulesEngine.add_counters`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "each_opponent"})],
            trigger={
                "event": "STEP_BEGIN", "filter": {"step": "end"},
                "active_if": {"kind": "you_placed_counter_on_creature_this_turn"},
            },
        ),
    ]


register("Lasting Tarfire", _lasting_tarfire)


def _oft_nabbed_goat() -> list[AbilitySpec]:
    """{1}: Draw a card. Gain control of this creature and put a -1/-1
    counter on it. Only your opponents may activate this ability and only
    as a sorcery.
    When this creature dies, if it had one or more -1/-1 counters on it,
    its owner draws that many cards and each other player loses that much
    life.

    Authored: the opponent-only activated ability
    (`ActivationCost.only_opponents_may_activate` — new inverse of
    Mercenaries' `any_player_may_activate`; sorcery-speed) whose effect
    body is a plain activator draw, `gain_control_by_source`
    (``recipient="activator"``, new branch — control moves to whoever
    activated it, RULE 602.2b) and a self ``add_counters``; and the dies
    trigger — new `OwnerDrawOthersLosePerDyingCounterEffect`
    ("owner_draw_others_lose_per_dying_counter"), gated by the trigger-level
    ``dying_had_counter`` intervening-if.
    """
    return [
        AbilitySpec(
            "activated",
            [
                # `gain_control_by_source` runs first so the plain untargeted
                # ``draw`` / self ``add_counters`` below resolve for the
                # activator (RULE 602.2b "you" = whoever activated it), which
                # both read off the source's *current* controller. Printed
                # order is "Draw a card. Gain control …"; nothing between the
                # two clauses observes the pre-swap state, so the reorder has
                # no observable effect.
                EffectSpec("gain_control_by_source", {"recipient": "activator"}),
                EffectSpec("draw", {"count": 1}),
                EffectSpec("add_counters", {"count": 1, "kind": "-1/-1"}),
            ],
            cost={"mana": "{1}", "only_opponents_may_activate": True,
                  "sorcery_speed_only": True},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("owner_draw_others_lose_per_dying_counter", {"counter_kind": "-1/-1"})],
            trigger={"event": "DIES", "condition": {"subject": "self"},
                     "dying_had_counter": "-1/-1"},
        ),
    ]


register("Oft-Nabbed Goat", _oft_nabbed_goat)


def _ferrafor_young_yew() -> list[AbilitySpec]:
    """When Ferrafor enters, create a number of 1/1 green Saproling creature
    tokens equal to the number of counters among creatures target player
    controls.
    {T}: Double the number of each kind of counter on target creature.

    Authored wholesale: the ETB trigger via new
    `CreateTokensPerCounterAmongTargetPlayerCreaturesEffect` (targets a
    player, counts every counter on that player's creatures), and the tap
    ability via new reusable `DoubleCountersOnTargetEffect` (RULE 701.19).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_tokens_per_counter_among_target_player_creatures", {
                "power": 1, "toughness": 1, "colors": ["G"], "subtypes": ["Saproling"],
                "token_name": "Saproling",
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("double_counters_on_target", {"target_kind": "creature"})],
            cost={"text": "{T}"},
        ),
    ]


register("Ferrafor, Young Yew", _ferrafor_young_yew)


def _everlasting_torment() -> list[AbilitySpec]:
    """Players can't gain life.
    Damage can't be prevented.
    All damage is dealt as though its source had wither.

    Registered wholesale, so all three standing statics are authored:
    ``prevent_all_life_gain`` (already parser-claimed on its own),
    ``damage_cant_be_prevented`` (new marker static — RULE 615, consulted by
    `RulesEngine._run_replacement_loop`), and ``global_wither`` (new marker
    static — RULE 609.4b as-though, consulted by `RulesEngine.deal_damage`).
    """
    return [
        AbilitySpec("static", [EffectSpec("prevent_all_life_gain", {})]),
        AbilitySpec("static", [EffectSpec("damage_cant_be_prevented", {})]),
        AbilitySpec("static", [EffectSpec("global_wither", {})]),
    ]


register("Everlasting Torment", _everlasting_torment)


def _cathartic_pyre() -> list[AbilitySpec]:
    """Choose one —
    • Cathartic Pyre deals 3 damage to target creature or planeswalker.
    • Discard up to two cards, then draw that many cards.

    Authored: the whole modal spell (the fail-closed parser can't claim the
    "choose one —" block while mode 2 is an unmodelled family). Mode 1 is an
    ordinary ``damage`` to ``creature_or_planeswalker``; mode 2 is the new
    `DiscardUpToThenDrawThatManyEffect` ("discard_up_to_then_draw_that_many").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("damage", {"amount": 3, "target_kind": "creature_or_planeswalker"})],
                    [EffectSpec("discard_up_to_then_draw_that_many", {"count": 2})],
                ],
                "descriptions": [
                    "~ fügt einer Zielkreatur oder einem Zielplaneswalker 3 Schadenspunkte zu.",
                    "Wirf bis zu zwei Karten ab, ziehe dann so viele Karten.",
                ],
            },
        )
    ]


register("Cathartic Pyre", _cathartic_pyre)


def _eventides_shadow() -> list[AbilitySpec]:
    """Remove any number of counters from among permanents on the
    battlefield. You draw cards and lose life equal to the number of
    counters removed this way.

    Authored: new bespoke `RemoveCountersFromAmongThenDrawLoseLifeEffect`
    ("remove_counters_from_among_then_draw_lose_life") — an ``optional``
    `_request_choose_objects` over counter-bearing permanents
    (action ``strip_all_counters``), then a draw + life-loss equal to the
    battlefield counter-total delta.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("remove_counters_from_among_then_draw_lose_life", {})],
        )
    ]


register("Eventide's Shadow", _eventides_shadow)


def _pucas_covenant() -> list[AbilitySpec]:
    """Whenever a creature you control with a counter on it dies, you may
    return another target permanent card with mana value less than or equal
    to the number of counters on that creature from your graveyard to your
    hand. Do this only once each turn.

    Authored: a DIES trigger over the C3a "creature you control with a
    counter on it" group subject, with ``limit`` (RULE 603.2 "…only once
    each turn"). The return targets a `graveyard_permanent` with the new
    dynamic `max_mana_value="trigger_dying_counters"` bound — resolved in
    `targeting.legal_targets` from the DIES event's snapshotted counter
    total (RULE 400.7). "another" (RULE 109.5, excluding the just-died
    creature itself) is a minor accepted precision loss, in line with this
    file's RULE 115 norms.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_permanent", "destination": "hand",
                "optional": True, "max_mana_value": "trigger_dying_counters",
            })],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature",
                              "controller": "you", "has_counter": True, "other": False},
                "limit": True,
            },
        )
    ]


register("Puca's Covenant", _pucas_covenant)


def _burning_curiosity() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may blight 1. (You may
    put a -1/-1 counter on a creature you control.)
    Exile the top two cards of your library. If this spell's additional cost
    was paid, exile the top three cards instead. Until the end of your next
    turn, you may play those cards.

    Authored: the optional ``blight 1`` additional cost
    (`additional_cost={"blight": 1}` + ``additional_cost_optional``) and an
    ``impulsive_draw`` whose count is overridden 2 -> 3 by the new
    ``count_if_additional_cost_paid`` param (RULE 614 "instead", gated on
    `GameObject.additional_cost_paid`). "Until end of your next turn" is
    `impulsive_draw`'s default window.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("impulsive_draw", {"count": 2, "count_if_additional_cost_paid": 3})],
            additional_cost={"blight": 1},
            additional_cost_optional=True,
        )
    ]


register("Burning Curiosity", _burning_curiosity)
