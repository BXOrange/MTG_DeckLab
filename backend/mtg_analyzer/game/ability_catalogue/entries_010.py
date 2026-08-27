"""Card -> AbilitySpec catalogue entries, part 010 of 016.

Mechanically split, in original file order, from the single flat
`ability_catalogue.py` module (now `core.py` for the shared registry
infrastructure + this package's `entries_NNN.py` files for the actual
per-card factories). Boundaries are purely positional -- not organized
by mechanic or card type -- see `__init__.py` for the full picture.
"""

from __future__ import annotations

from ...models.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

def _transmogrify() -> list[AbilitySpec]:
    """Exile target creature. That creature's controller reveals cards
    from the top of their library until they reveal a creature card. That
    player puts that card onto the battlefield, then shuffles the rest
    into their library.

    — MEC-12 (cEDH Kinnan). Transmogrify's own exile-mode sibling of
    Polymorph, sharing the same new effect (`mode="exile"` — no "can't be
    regenerated" clause to carry, since exile isn't destruction to begin
    with).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_exile_then_controller_reveal_creature", {
                "target_kind": "creature", "mode": "exile", "criteria": "Creature",
            })],
            raw_text="Exile target creature. That creature's controller "
                     "reveals cards from the top of their library until they "
                     "reveal a creature card. That player puts that card onto "
                     "the battlefield, then shuffles the rest into their "
                     "library.",
        ),
    ]


register("Transmogrify", _transmogrify)


def _reality_scramble() -> list[AbilitySpec]:
    """Put target permanent you own on the bottom of your library. Reveal
    cards from the top of your library until you reveal a card that shares
    a card type with that permanent. Put that card onto the battlefield
    and the rest on the bottom of your library in a random order.
    Retrace (You may cast this card from your graveyard by discarding a
    land card in addition to paying its other costs.)

    — MEC-12 (cEDH Kinnan). `ReturnToLibraryThenDigSharedTypeEffect` reads
    the type-matching predicate live off the just-bottomed permanent's own
    printed type words rather than a fixed criteria (see its own
    docstring). Retrace is a printed keyword (`Card.keywords`), recognized
    independently of this catalogue entry — nothing to model here.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_library_then_dig_shared_type", {
                "target_kind": "permanent_you_control",
            })],
            raw_text="Put target permanent you own on the bottom of your "
                     "library. Reveal cards from the top of your library "
                     "until you reveal a card that shares a card type with "
                     "that permanent. Put that card onto the battlefield and "
                     "the rest on the bottom of your library in a random "
                     "order.\nRetrace (You may cast this card from your "
                     "graveyard by discarding a land card in addition to "
                     "paying its other costs.)",
        ),
    ]


register("Reality Scramble", _reality_scramble)


def _sink_into_stupor() -> list[AbilitySpec]:
    """Return target spell or nonland permanent an opponent controls to
    its owner's hand.

    — MEC-12 (cEDH Kinnan/M-K). `ReturnToHandEffect`'s new
    ``spell_or_permanent`` flag routes through `RulesEngine.
    bounce_spell_or_permanent` (a still-on-the-stack target needs pulling
    out of `GameState.stack`, which the ordinary battlefield/zone-based
    `return_to_hand` has no way to reach) instead of the plain bounce.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "spell_or_nonland_permanent_you_dont_control",
                "spell_or_permanent": True,
            })],
            raw_text="Return target spell or nonland permanent an opponent "
                     "controls to its owner's hand.",
        ),
    ]


register("Sink into Stupor", _sink_into_stupor)
register("Sink into Stupor // Soporific Springs", _sink_into_stupor)


def _spellskite() -> list[AbilitySpec]:
    """{U/P}: Change a target of target spell or ability to this creature.
    ({U/P} can be paid with either {U} or 2 life.)

    — MEC-12 (cEDH Kinnan). `ChangeTargetEffect`'s new ``redirect_to_source``
    flag (built for this card and Hydroelectric Specimen together) — not a
    free choice among every legal alternative the way Misdirection/
    Deflecting Swat's own player-facing pick is, but forced onto Spellskite
    itself if that's even legal. No "you may" printed, so ``optional`` stays
    False: with exactly one candidate alternative (itself), that auto-applies.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("change_target", {
                "spell_or_ability": True, "redirect_to_source": True,
            })],
            cost={"mana": "{U/P}"},
            raw_text="{U/P}: Change a target of target spell or ability to "
                     "this creature. ({U/P} can be paid with either {U} or 2 "
                     "life.)",
        ),
    ]


register("Spellskite", _spellskite)


def _hydroelectric_specimen() -> list[AbilitySpec]:
    """When Hydroelectric Specimen enters, you may change the target of
    target instant or sorcery spell with a single target to Hydroelectric
    Specimen.

    — MEC-12 (cEDH Kinnan). The ETB-triggered, "you may" sibling of
    Spellskite's activated ability, sharing the same `redirect_to_source`
    primitive — narrowed to instant/sorcery spells by `ChangeTargetEffect`'s
    new ``card_types`` param (`targeting._spell_matches_filter`'s existing
    ``card_types`` key, previously only reachable via `CounterSpellEffect`'s
    own ``card_types``, never `ChangeTargetEffect`'s).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("change_target", {
                "card_types": ["instant", "sorcery"], "single_target": True,
                "redirect_to_source": True, "optional": True,
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="When ~ enters, you may change the target of target "
                     "instant or sorcery spell with a single target to ~.",
        ),
    ]


register("Hydroelectric Specimen", _hydroelectric_specimen)
register("Hydroelectric Specimen // Hydroelectric Laboratory", _hydroelectric_specimen)


def _void_winnower() -> list[AbilitySpec]:
    """Your opponents can't cast spells with even mana values. (Zero is
    even.)
    Your opponents can't block with creatures with even mana values.

    — MEC-12 (cEDH Kinnan). Two new filter keys, both keyed off "Zero is
    even": `cast_prohibition`'s new ``even_mana_value`` param
    (`continuous.cast_prohibited`) for the cast-side clause, and
    `combat.matches_object_filter`'s new ``even_mana_value`` key (checked
    against the *blocker itself* via the new `cant_block_self_filtered`
    combat-restriction kind — every existing blocker-side kind filters the
    *attacker*, which isn't what this card's blocker-own-characteristics
    restriction needs) for the block-side one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents", "even_mana_value": True,
            })],
            raw_text="Your opponents can't cast spells with even mana "
                     "values. (Zero is even.)",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "kind": "cant_block_self_filtered",
                "filter": {"even_mana_value": True},
                "affects": "creatures_opponents_control",
            })],
            raw_text="Your opponents can't block with creatures with even "
                     "mana values.",
        ),
    ]


register("Void Winnower", _void_winnower)


def _nyxbloom_ancient() -> list[AbilitySpec]:
    """Trample
    If you tap a permanent for mana, it produces three times as much of
    that mana instead.

    — MEC-12 (cEDH Kinnan). The new `mana_multiplier` static
    (`continuous.mana_production_multiplier_for`, consulted directly by
    `GameEngine.tap_for_mana`) — Trample is a printed keyword, recognized
    independently of this entry.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("mana_multiplier", {"multiplier": 3})],
            raw_text="If you tap a permanent for mana, it produces three "
                     "times as much of that mana instead.",
        ),
    ]


register("Nyxbloom Ancient", _nyxbloom_ancient)


def _trinisphere() -> list[AbilitySpec]:
    """As long as this artifact is untapped, each spell that would cost
    less than three mana to cast costs three mana to cast instead.

    — MEC-12 (cEDH Kinnan). The new `cost_floor_for`/``min_generic``
    "costs no less than N" primitive — a floor, not the existing
    ``increase``/``generic`` additive tax (see `continuous.cost_floor_for`'s
    own docstring for why the two are kept apart). ``active_if:
    source_untapped`` is the existing RULE 613.6 gate vocabulary, reused
    as-is.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "all_spells", "min_generic": 3,
                "active_if": {"kind": "source_untapped"},
            })],
            raw_text="As long as this artifact is untapped, each spell that "
                     "would cost less than three mana to cast costs three "
                     "mana to cast instead.",
        ),
    ]


register("Trinisphere", _trinisphere)


def _tezzeret_the_seeker() -> list[AbilitySpec]:
    """+1: Untap up to two target artifacts.
    −X: Search your library for an artifact card with mana value X or
    less, put it onto the battlefield, then shuffle.
    −5: Artifacts you control become artifact creatures with base power
    and toughness 5/5 until end of turn.

    — MEC-12 (cEDH Kinnan). Hand-authored whole (rather than reusing the
    parser's own claimed +1 spec) since that spec's ``target_kind`` reads
    "permanent" instead of "artifact" — fixed here rather than left
    inconsistent across the card's three abilities. The −X search is the
    existing `search` effect with the ``"x"`` sentinel
    (`RulesEngine._substitute_x` already walks a ``criteria`` dict's
    ``max_mana_value`` for exactly this). The −5 is `GrantUntilEffect`
    wrapping a `type_change` static scoped to ``affects="artifacts_you_
    control"`` — untargeted (``target_kind=None``), since nothing here is a
    RULE 115 target at all, just every artifact the activating player
    already controls.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {
                "target_kind": "artifact", "count": 2, "optional": True, "untap": True,
            })],
            cost={"loyalty": 1},
            raw_text="+1: Untap up to two target artifacts.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact", "max_mana_value": "x"},
                "destination": "battlefield",
            })],
            cost={"loyalty": "-x"},
            raw_text="−X: Search your library for an artifact card with mana "
                     "value X or less, put it onto the battlefield, then "
                     "shuffle.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "type_change", "params": {
                    "affects": "artifacts_you_control", "add_types": ["creature"],
                    "power": 5, "toughness": 5,
                }},
                "duration": "end_of_turn", "target_kind": None,
            })],
            cost={"loyalty": -5},
            raw_text="−5: Artifacts you control become artifact creatures "
                     "with base power and toughness 5/5 until end of turn.",
        ),
    ]


register("Tezzeret the Seeker", _tezzeret_the_seeker)


def _treasure_vault() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {X}{X}, {T}, Sacrifice this land: Create X Treasure tokens.

    — MEC-12 (cEDH Kinnan). The plain "{T}: Add {C}." mana ability needs no
    entry at all here — `game/mana_abilities.py`'s `mana_abilities_for`
    reads it straight off `Card.oracle_text` via its own regex, completely
    independent of catalogue registration (unlike `parse_oracle`'s
    AbilitySpec pipeline, which *does* turn off once a name is registered).
    Only the X-cost second ability needs hand-authoring. ``"count": "x"``
    on `create_token` rides the same ``"x"`` sentinel the ``{X}{X}`` cost
    itself does (`RulesEngine._substitute_x` walks a plain effect ``count``
    attribute).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {"count": "x", "token_name": "Treasure"})],
            cost={"text": "{X}{X}", "tap": True, "sacrifice": "self"},
            raw_text="{X}{X}, {T}, Sacrifice this land: Create X Treasure "
                     "tokens.",
        ),
    ]


register("Treasure Vault", _treasure_vault)


def _narset_parter_of_veils() -> list[AbilitySpec]:
    """Each opponent can't draw more than one card each turn.
    −2: Look at the top four cards of your library. You may reveal a
    noncreature, nonland card from among them and put it into your hand.
    Put the rest on the bottom of your library in a random order.

    — MEC-12 (cEDH M-K). The static is `draw_limit`'s new ``affects``
    param (default was hardwired to ``"all"``, Spirit-of-the-Labyrinth-
    shaped) — see `continuous.max_draws_per_turn`'s own docstring. The
    loyalty ability is `impulsive_look` with the new ``without_type``
    `card_query` key (`"creature"`/`"land"`, AND-combined — RULE 205's
    main types only) and the new ``miss_destination="library_bottom_
    random"`` (a *group* shuffle of the un-revealed cards, not each one
    independently bottomed in reveal order).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"affects": "opponents", "max_per_turn": 1})],
            raw_text="Each opponent can't draw more than one card each turn.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("impulsive_look", {
                "count": 4, "criteria": {"without_type": ["creature", "land"]},
                "hit_destination": "hand", "miss_destination": "library_bottom_random",
                "optional": True,
            })],
            cost={"loyalty": -2},
            raw_text="−2: Look at the top four cards of your library. You "
                     "may reveal a noncreature, nonland card from among "
                     "them and put it into your hand. Put the rest on the "
                     "bottom of your library in a random order.",
        ),
    ]


register("Narset, Parter of Veils", _narset_parter_of_veils)


def _kediss_emberclaw_familiar() -> list[AbilitySpec]:
    """Whenever a commander you control deals combat damage to an
    opponent, it deals that much damage to each other opponent.
    Partner (You can have two commanders if both have partner.)

    — MEC-12 (cEDH M-K). The new top-level ``contributor_is_commander``
    trigger key (RULE 903's own designation, stamped onto the existing
    MEC-29 aggregate combat-damage event by `GameEngine.
    _apply_combat_damage` — the same "no single acting object, so the
    event carries the aggregate characteristic itself" reasoning as
    `contributor_power_at_least`/`contributor_subtype`, not a live
    per-object `_build_group_ok` filter, since this event names no
    instance to look one up on) combined with the new
    ``each_other_opponent`` `DealDamageEffect` selector (``each_opponent``
    minus whichever opponent the firing event itself already hit). Partner
    is a printed keyword, recognized independently of this entry.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "amount_from_trigger_event": "amount", "selector": "each_other_opponent",
            })],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "group", "controller": "you"},
                "contributor_is_commander": True,
            },
            raw_text="Whenever a commander you control deals combat damage "
                     "to an opponent, it deals that much damage to each "
                     "other opponent.",
        ),
    ]


register("Kediss, Emberclaw Familiar", _kediss_emberclaw_familiar)


def _malcolm_keen_eyed_navigator() -> list[AbilitySpec]:
    """Flying
    Whenever one or more Pirates you control deal damage to your
    opponents, you create a Treasure token for each opponent dealt
    damage. (It's an artifact with "{T}, Sacrifice this token: Add one
    mana of any color.")
    Partner (You can have two commanders if both have partner.)

    — MEC-12 (cEDH M-K). **Documented simplification**: scoped to *combat*
    damage (the new ``contributor_subtype`` trigger key on the existing
    MEC-29 aggregate event, `GameEngine._apply_combat_damage`'s own
    ``subtypes`` field — the union of every contributing creature's
    subtypes that step), not the printed card's fully general "deal
    damage" — noncombat damage from a controlled Pirate is a vanishingly
    rare case this template doesn't reach. "A Treasure for each opponent
    dealt damage" needs no explicit count: the aggregate event already
    fires once per (controller, opponent-hit) pair (MEC-29), so each
    firing is already scoped to exactly one opponent. Flying/Partner are
    printed keywords, recognized independently of this entry.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "group", "controller": "you"},
                "contributor_subtype": "pirate",
            },
            raw_text="Whenever one or more Pirates you control deal combat "
                     "damage to a player, you create a Treasure token for "
                     "that opponent.",
        ),
    ]


register("Malcolm, Keen-Eyed Navigator", _malcolm_keen_eyed_navigator)


def _glint_horn_buccaneer() -> list[AbilitySpec]:
    """Haste
    Whenever you discard a card, this creature deals 1 damage to each
    opponent.
    {1}{R}, Discard a card: Draw a card. Activate only if this creature
    is attacking.

    — MEC-12 (cEDH M-K). The new ``"DISCARD"`` row in `effect_binder.
    _GROUP_CONTROLLER_EVENT_KEYS` (a plain player-subject trigger,
    ``{"subject": "you"}`` — the same shape "whenever you scry/gain
    life/draw a card" already use, just missing this one event) closes
    the first ability; the second's "activate only if attacking" is
    already-general `ActivationCost.activation_condition` machinery
    (`static_conditions`' existing ``source_attacking`` kind, PAR-10) —
    no new primitive, just the first real card to combine the two. Haste
    is a printed keyword, recognized independently of this entry.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "each_opponent"})],
            trigger={"event": "DISCARD", "condition": {"subject": "you"}},
            raw_text="Whenever you discard a card, ~ deals 1 damage to "
                     "each opponent.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={
                "mana": "{1}{R}", "discard": 1,
                "activation_condition": {"kind": "source_attacking"},
            },
            raw_text="{1}{R}, Discard a card: Draw a card. Activate only "
                     "if ~ is attacking.",
        ),
    ]


register("Glint-Horn Buccaneer", _glint_horn_buccaneer)


def _horizon_of_progress() -> list[AbilitySpec]:
    """{T}, Pay 1 life: Add one mana of any type that a land you control
    could produce.
    {3}, {T}: You may put a land card from your hand onto the
    battlefield tapped.
    {1}, {T}, Sacrifice this land: Draw a card.

    — MEC-12 (cEDH M-K). The first ability needs no entry at all —
    `mana_abilities_for` reads "any type a land you control could
    produce" straight off oracle text, independent of catalogue
    registration (same reasoning as Treasure Vault's plain mana ability).
    The third is already parser-claimed for free (`reuse` confirms it —
    restated here since registering this name turns the parser fallback
    off for *every* ability, not just the unclaimed one). Only the second
    needs real hand-authoring: `put_from_hand_onto_battlefield`'s new
    ``tapped`` flag.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("put_from_hand_onto_battlefield", {
                "criteria": "Land", "count": 1, "tapped": True,
            })],
            cost={"text": "{3}, {T}"},
            raw_text="{3}, {T}: You may put a land card from your hand "
                     "onto the battlefield tapped.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{1}, {T}, Sacrifice ~"},
            raw_text="{1}, {T}, Sacrifice ~: Draw a card.",
        ),
    ]


register("Horizon of Progress", _horizon_of_progress)


def _commandeer() -> list[AbilitySpec]:
    """You may exile two blue cards from your hand rather than pay this
    spell's mana cost.
    Gain control of target noncreature spell. You may choose new targets
    for it. (If that spell is an artifact, enchantment, or planeswalker,
    the permanent enters under your control.)

    — MEC-12 (cEDH M-K). The alt cost is already parser-claimed for free
    (`reuse` confirms it, `AbilitySpec.alt_cost`'s existing
    ``exile_hand_card_color_count`` key). The real gain-control-of-a-
    *spell* effect is new: `GainControlOfSpellEffect`/`RulesEngine.
    gain_control_of_spell` — see its own docstring for why only
    `StackItem.controller_id` (not a battlefield zone-change) needs to
    move, and why the optional retarget runs *before* that flip.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("gain_control_of_spell", {})],
            raw_text="Gain control of target noncreature spell. You may "
                     "choose new targets for it.",
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"exile_hand_card_color_count": [2, "U"]},
            raw_text="You may exile two blue cards from your hand rather "
                     "than pay this spell's mana cost.",
        ),
    ]


register("Commandeer", _commandeer)


def _days_undoing() -> list[AbilitySpec]:
    """Each player shuffles their hand and graveyard into their library,
    then draws seven cards. If it's your turn, end the turn. (Exile all
    spells and abilities from the stack, including this card. Discard
    down to your maximum hand size. Damage wears off, and "this turn"
    and "until end of turn" effects end.)

    — MEC-12 (cEDH M-K). `wheel` (Timetwister) covers the first sentence
    unchanged. "If it's your turn, end the turn" is the new
    ``is_your_turn`` `ConditionalEffect` gate wrapping the new
    `end_the_turn`/`EndTheTurnEffect` (RulesEngine can't reach
    `GameEngine._turn_steps`/`_cursor` directly, so it exiles the stack
    now and queues `GameState.end_turn_requested` for `GameEngine.
    advance_step` to drain — see both docstrings). "Including this card"
    is a trailing self-exile (``target_kind=None``), the same override
    `_apply_stack_item` already gives `ShuffleSelfIntoLibraryEffect` —
    without it this card would go to its owner's graveyard as normal
    resolution, not exile.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("wheel", {"draw_count": 7}),
                EffectSpec("end_the_turn", {}, condition={"is_your_turn": True}),
                EffectSpec("exile", {"target_kind": None}),
            ],
            raw_text="Each player shuffles their hand and graveyard into "
                     "their library, then draws seven cards. If it's your "
                     "turn, end the turn.",
        ),
    ]


register("Day's Undoing", _days_undoing)


def _lukka_coppercoat_outcast() -> list[AbilitySpec]:
    """+1: Exile the top three cards of your library. Creature cards
    exiled this way gain "You may cast this card from exile as long as
    you control a Lukka planeswalker."
    −2: Exile target creature you control, then reveal cards from the top
    of your library until you reveal a creature card with greater mana
    value. Put that card onto the battlefield and the rest on the bottom
    of your library in a random order.
    −7: Each creature you control deals damage equal to its power to
    each opponent.

    — MEC-12 (cEDH M-K). The +1 is the new `exile_top_then_grant_
    conditional_cast`/`GameState.exile_cast_condition` — a genuinely
    standing (never turn-swept) exile cast permission, unlike every other
    "exile, may cast later" grant in this engine, gated on the new
    ``planeswalkers_you_control_of_type_`` count selector via the
    already-general `control_count` static condition. The −2 is
    `exile_then_reveal_greater_mana_value` (the exiled target's own mana
    value becomes the dig's floor, read at resolution). The −7 is
    `each_creature_you_control_damages_each_opponent`, a double mass
    effect no existing `DealDamageEffect` selector already composes.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exile_top_then_grant_conditional_cast", {
                "count": 3,
                "condition": {
                    "kind": "control_count",
                    "selector": "planeswalkers_you_control_of_type_lukka",
                    "min": 1,
                },
            })],
            cost={"loyalty": 1},
            raw_text='+1: Exile the top three cards of your library. '
                     'Creature cards exiled this way gain "You may cast '
                     'this card from exile as long as you control a Lukka '
                     'planeswalker."',
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("exile_then_reveal_greater_mana_value", {
                "target_kind": "creature_you_control",
            })],
            cost={"loyalty": -2},
            raw_text="−2: Exile target creature you control, then reveal "
                     "cards from the top of your library until you reveal "
                     "a creature card with greater mana value. Put that "
                     "card onto the battlefield and the rest on the bottom "
                     "of your library in a random order.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("each_creature_you_control_damages_each_opponent", {})],
            cost={"loyalty": -7},
            raw_text="−7: Each creature you control deals damage equal to "
                     "its power to each opponent.",
        ),
    ]


register("Lukka, Coppercoat Outcast", _lukka_coppercoat_outcast)


def _enduring_vitality() -> list[AbilitySpec]:
    """Vigilance
    Creatures you control have "{T}: Add one mana of any color."
    When Enduring Vitality dies, if it was a creature, return it to the
    battlefield under its owner's control. It's an enchantment. (It's not
    a creature.)

    — MEC-12 (cEDH Kinnan). Vigilance and the granted mana ability are
    both already parser-claimed for free (`reuse` confirms it — restated
    here since registering the name turns that fallback off for every
    ability, not just the unclaimed one). The dies-trigger is the new
    `dies_return_as_enchantment`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keyword": "vigilance", "affects": "self"})],
            raw_text="Vigilance",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "creatures_you_control", "mana": [{"C": 1}],
            })],
            raw_text='Creatures you control have "{T}: Add one mana of any '
                     'color."',
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("dies_return_as_enchantment", {})],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
            raw_text="When ~ dies, if it was a creature, return it to the "
                     "battlefield under its owner's control. It's an "
                     "enchantment.",
        ),
    ]


register("Enduring Vitality", _enduring_vitality)


def _faerie_mastermind() -> list[AbilitySpec]:
    """Flash
    Flying
    Whenever an opponent draws their second card each turn, you draw a
    card.
    {3}{U}: Each player draws a card.

    — MEC-12 (cEDH Kinnan). Flash/Flying and the activated "each player
    draws" are already parser-claimed for free. Only the second-draw
    trigger needs the new ``is_nth_draw_this_turn`` top-level trigger key.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "DRAW", "condition": {"subject": "group", "controller": "not_you"},
                "is_nth_draw_this_turn": 2,
            },
            raw_text="Whenever an opponent draws their second card each "
                     "turn, you draw a card.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1, "selector": "each_player"})],
            cost={"mana": "{3}{U}"},
            raw_text="{3}{U}: Each player draws a card.",
        ),
    ]


register("Faerie Mastermind", _faerie_mastermind)


def _into_the_flood_maw() -> list[AbilitySpec]:
    """Gift a tapped Fish (You may promise an opponent a gift as you cast
    this spell. If you do, they create a tapped 1/1 blue Fish creature
    token before its other effects.)
    Return target creature an opponent controls to its owner's hand. If
    the gift was promised, instead return target nonland permanent an
    opponent controls to its owner's hand.

    — MEC-12 (cEDH Kinnan). **Documented simplification**: the Gift
    mechanic (RULE-adjacent WOE ability word — a cast-time "promise a
    gift" branch with no engine primitive anywhere yet) is dropped
    entirely; this always resolves as the un-gifted base mode ("return
    target creature an opponent controls to its owner's hand"), never
    offering the opponent a Fish or the "any nonland permanent" upgrade.
    Building Gift generally is real, standalone engine work — a genuinely
    new interactive cast-time choice threaded through casting/targeting —
    not something to fold into one card's own entry.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {"target_kind": "creature_you_dont_control"})],
            raw_text="Return target creature an opponent controls to its "
                     "owner's hand.",
        ),
    ]


register("Into the Flood Maw", _into_the_flood_maw)


def _invasion_of_ikoria() -> list[AbilitySpec]:
    """(As a Siege enters, choose an opponent to protect it. You and
    others can attack it. When it's defeated, exile it, then cast it
    transformed.)
    When this Siege enters, search your library and/or graveyard for a
    non-Human creature card with mana value X or less and put it onto
    the battlefield. If you search your library this way, shuffle.

    — MEC-12 (cEDH Kinnan). The Siege reminder text is the existing
    generic RULE 310 battle machinery, not modeled here. The search
    itself already fully supports "library and/or graveyard"
    (`SearchLibraryEffect`'s existing ``zones`` param — always shuffles
    when "library" is among them, RULE 701.19e, matching "if you search
    your library this way, shuffle" for the common case of always
    searching both). The only new piece is the ``"source_x_paid"``
    criteria sentinel: this ETB fires well after the original casting
    resolution ends, so the existing bare ``"x"`` sentinel (tied to
    *this* stack item's own announced X, which is 0 for a trigger) can't
    reach the permanent's announced X the way it does for a spell's own
    effects — `GameObject.x_paid`, stamped once at cast time, is read
    instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {
                    "type": "Creature", "without_type": "human",
                    "max_mana_value": "source_x_paid",
                },
                "destination": "battlefield",
                "zones": ["library", "graveyard"],
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="When this Siege enters, search your library and/or "
                     "graveyard for a non-Human creature card with mana "
                     "value X or less and put it onto the battlefield. If "
                     "you search your library this way, shuffle.",
        ),
    ]


register("Invasion of Ikoria", _invasion_of_ikoria)
register("Invasion of Ikoria // Zilortha, Apex of Ikoria", _invasion_of_ikoria)


def _machine_gods_effigy() -> list[AbilitySpec]:
    """You may have this artifact enter as a copy of any creature on the
    battlefield, except it's an artifact and it has "{T}: Add {U}." (It's
    not a creature.)
    {T}: Add {U}.

    — MEC-12 (cEDH Kinnan). `EnterAsCopyReplacement`'s new
    ``grant_mana_option`` param — RULE 707.2's copy replaces the card's
    own printed text (including its own real "{T}: Add {U}." line) with
    the copied creature's, so that ability has to be re-granted as part
    of this same "except" clause rather than assumed to survive; applied
    as a fresh `StaticAbility` on the copy itself once `become_copy`
    resolves (`GameObject.granted_mana_options` is a read-only,
    every-recompute-rederived property, not a settable field). The plain
    "{T}: Add {U}." second line needs no entry of its own — read straight
    off oracle text by `mana_abilities_for`, same as Treasure Vault/
    Horizon of Progress — but note it only actually produces mana while
    this artifact *hasn't* copied anything (a successful copy overwrites
    it, which is exactly why the grant above exists).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature", "add_types": ["artifact"],
                "grant_mana_option": {"U": 1},
                "optional": True,
            })],
            raw_text="You may have ~ enter as a copy of any creature on "
                     'the battlefield, except it\'s an artifact and it has '
                     '"{T}: Add {U}."',
        ),
    ]


register("Machine God's Effigy", _machine_gods_effigy)


def _moonsilver_key() -> list[AbilitySpec]:
    """{1}, {T}, Sacrifice this artifact: Search your library for an
    artifact card with a mana ability or a basic land card, reveal it,
    put it into your hand, then shuffle.

    — MEC-12 (cEDH Kinnan). The new `card_query` ``"or"``/
    ``"has_mana_ability"`` keys — the first real compound ("X or Y")
    search criteria in the catalogue; every prior search criteria dict
    was a plain AND.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {
                    "or": [
                        {"type": "Artifact", "has_mana_ability": True},
                        {"basic": True},
                    ],
                },
                "destination": "hand",
            })],
            cost={"text": "{1}, {T}, Sacrifice ~"},
            raw_text="{1}, {T}, Sacrifice ~: Search your library for an "
                     "artifact card with a mana ability or a basic land "
                     "card, reveal it, put it into your hand, then "
                     "shuffle.",
        ),
    ]


register("Moonsilver Key", _moonsilver_key)


def _nezahal_primal_tide() -> list[AbilitySpec]:
    """This spell can't be countered.
    You have no maximum hand size.
    Whenever an opponent casts a noncreature spell, draw a card.
    Discard three cards: Exile Nezahal. Return it to the battlefield
    tapped under its owner's control at the beginning of the next end
    step.

    — MEC-12 (cEDH Kinnan). The first three abilities are already
    parser-claimed for free (`reuse` confirms it — restated here since
    registering the name turns the parser fallback off for all of them,
    not just the unclaimed one). The activated ability is the new
    `return_self_to_battlefield`, run via the existing RULE 603.7
    `CreateDelayedTriggerEffect`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
            raw_text="This spell can't be countered.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("no_max_hand_size", {"affects": "you"})],
            raw_text="You have no maximum hand size.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "SPELL_CAST", "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
            raw_text="Whenever an opponent casts a noncreature spell, "
                     "draw a card.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": None}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any",
                    "effects": [{"type": "return_self_to_battlefield", "params": {"tapped": True}}],
                    "description": "Nezahal: return tapped at the next end step",
                }),
            ],
            cost={"discard": 3},
            raw_text="Discard three cards: Exile ~. Return it to the "
                     "battlefield tapped under its owner's control at the "
                     "beginning of the next end step.",
        ),
    ]


register("Nezahal, Primal Tide", _nezahal_primal_tide)


def _thrasios_triton_hero() -> list[AbilitySpec]:
    """{4}: Scry 1, then reveal the top card of your library. If it's a
    land card, put it onto the battlefield tapped. Otherwise, draw a
    card.
    Partner (You can have two commanders if both have partner.)

    — MEC-12 (cEDH Kinnan). `scry` (already general) chained with the new
    `reveal_top_then_land_battlefield_or_draw` — RULE 608.2's "suspend on
    a pending choice, resume once answered" already parks the second
    effect until scry's own interactive choice is settled, so no new
    sequencing primitive is needed, only the reveal-and-branch effect
    itself (a genuine singleton shape with nothing close enough to
    reuse). Partner is a printed keyword, recognized independently of
    this entry.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("scry", {"count": 1}),
                EffectSpec("reveal_top_then_land_battlefield_or_draw", {}),
            ],
            cost={"mana": "{4}"},
            raw_text="{4}: Scry 1, then reveal the top card of your "
                     "library. If it's a land card, put it onto the "
                     "battlefield tapped. Otherwise, draw a card.",
        ),
    ]


register("Thrasios, Triton Hero", _thrasios_triton_hero)


def _veil_of_summer() -> list[AbilitySpec]:
    """Draw a card if an opponent has cast a blue or black spell this
    turn. Spells you control can't be countered this turn. You and
    permanents you control gain hexproof from blue and from black until
    end of turn. (You and they can't be the targets of blue or black
    spells or abilities your opponents control.)

    — MEC-12 (cEDH Kinnan). **Documented simplification**: the third
    sentence ("You and permanents you control gain hexproof from blue
    and from black") is dropped — this engine's `combat.has_hexproof`
    is an unqualified RULE 702.11b flag with no "hexproof from `<quality>`"
    variant (RULE 702.11c), and there is no player-level hexproof/
    targetability check anywhere at all yet (every "player" target kind
    in `targeting.py` returns every living player unconditionally).
    Building qualified hexproof for both permanents and players is a
    real, standalone engine primitive, not something to wedge into this
    card's own entry. The other two clauses are real: the new
    ``opponent_cast_color_this_turn`` `ConditionalEffect` condition
    (`GameState.spell_colors_cast_this_turn`, tracked off `SPELL_CAST`
    the same way `cast_instant_or_sorcery_this_turn` already is) and the
    new `mark_your_spells_on_stack_cant_be_countered` (immediate) +
    `arm_spell_watcher`'s new ``repeat`` flag (for the rest of the turn).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec(
                    "draw", {"count": 1},
                    condition={"opponent_cast_color_this_turn": ["U", "B"]},
                ),
                EffectSpec("mark_your_spells_on_stack_cant_be_countered", {}),
                EffectSpec("arm_spell_watcher", {
                    "then_specs": [{"type": "mark_cant_be_countered", "params": {}}],
                    "repeat": True,
                }),
            ],
            raw_text="Draw a card if an opponent has cast a blue or black "
                     "spell this turn. Spells you control can't be "
                     "countered this turn.",
        ),
    ]


register("Veil of Summer", _veil_of_summer)


def _hullbreaker_horror() -> list[AbilitySpec]:
    """Flash
    This spell can't be countered.
    Whenever you cast a spell, choose up to one —
    • Return target spell you don't control to its owner's hand.
    • Return target nonland permanent to its owner's hand.

    — MEC-12 (cEDH Kinnan). Flash and "this spell can't be countered" are
    already parser-claimed for free. The modal trigger needs the new
    RULE 700.2 "choose *up to* one —" quantifier (`AbilitySpec.modes`'s
    new ``optional`` key, `TriggeredAbility.modes_optional`) — the 0-or-1
    sibling of the existing plain "choose one" (always exactly 1) and
    "choose one or both" (1 or 2) shapes, which had no way to express a
    real decline. The first mode's target is the new
    ``spell_you_dont_control`` kind (``ReturnToHandEffect``'s
    ``spell_or_permanent`` flag for the stack-aware bounce).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
            raw_text="This spell can't be countered.",
        ),
        AbilitySpec(
            "triggered",
            [],
            trigger={"event": "SPELL_CAST", "condition": {"subject": "you"}},
            modes={
                "choose": 1,
                "optional": True,
                "options": [
                    [EffectSpec("return_to_hand", {
                        "target_kind": "spell_you_dont_control", "spell_or_permanent": True,
                    })],
                    [EffectSpec("return_to_hand", {"target_kind": "nonland_permanent"})],
                ],
                "descriptions": [
                    "Return target spell you don't control to its owner's hand.",
                    "Return target nonland permanent to its owner's hand.",
                ],
            },
            raw_text="Whenever you cast a spell, choose up to one —\n"
                     "• Return target spell you don't control to its "
                     "owner's hand.\n"
                     "• Return target nonland permanent to its owner's "
                     "hand.",
        ),
    ]


register("Hullbreaker Horror", _hullbreaker_horror)


# ---------------------------------------------------------------------------
# MEC-12: Ojer cEDH — new core primitive (`EventType.ACTIVATED_ABILITY`,
# RULE 602.2) + oracle-text-blind reuse of the existing TAPPED_FOR_MANA
# "group"/"nonbasic" scoping (effect_binder.py) for the "punisher" family.
# ---------------------------------------------------------------------------


def _manabarbs() -> list[AbilitySpec]:
    """Whenever a player taps a land for mana, this enchantment deals 1
    damage to that player. — Manabarbs. The bare, untyped sibling of Price
    of Glory's own `TAPPED_FOR_MANA` consumer: no `"nonbasic"` filter, and
    `DealDamageEffect`'s existing `selector="event_player"` (Spellshock's
    shape) for "that player" instead of Price of Glory's reflexive-target
    destroy.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land"},
            },
            raw_text="Whenever a player taps a land for mana, this "
                     "enchantment deals 1 damage to that player.",
        )
    ]


register("Manabarbs", _manabarbs)


def _burning_earth() -> list[AbilitySpec]:
    """Whenever a player taps a nonbasic land for mana, this enchantment
    deals 1 damage to that player. — Burning Earth. Manabarbs' own
    `"nonbasic"` sibling — `effect_binder._build_group_ok`'s new supertype
    filter (a live board check, since "Basic" isn't a main type
    `object_types` carries or a subtype after the em dash).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land", "nonbasic": True},
            },
            raw_text="Whenever a player taps a nonbasic land for mana, "
                     "this enchantment deals 1 damage to that player.",
        )
    ]


register("Burning Earth", _burning_earth)


def _harsh_mentor() -> list[AbilitySpec]:
    """Whenever an opponent activates an ability of an artifact, creature,
    or land on the battlefield, if it isn't a mana ability, this creature
    deals 2 damage to that player. — Harsh Mentor. First consumer of the
    new `EventType.ACTIVATED_ABILITY` (`GameEngine.activate_ability`, RULE
    602.2) — mana abilities never reach that event at all (RULE 605.1a:
    they never use the stack, resolving instead through `tap_for_mana`/
    `activate_hand_mana_ability`), so "isn't a mana ability" needs no
    filter of its own. "of an artifact, creature, or land" is simplified to
    "of a permanent" (artifact/creature/land cover the overwhelming
    majority of real activated abilities; a planeswalker/battle/
    enchantment-only activated ability triggering this too is a narrow,
    documented over-trigger rather than a missed one).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Whenever an opponent activates an ability of an "
                     "artifact, creature, or land on the battlefield, if "
                     "it isn't a mana ability, this creature deals 2 "
                     "damage to that player.",
        )
    ]


register("Harsh Mentor", _harsh_mentor)


def _immolation_shaman() -> list[AbilitySpec]:
    """Whenever an opponent activates an ability of an artifact, creature,
    or land that isn't a mana ability, this creature deals 1 damage to
    that player.
    {3}{R}{R}: This creature gets +3/+3 and gains menace until end of turn.

    — Immolation Shaman. Harsh Mentor's own 1-damage sibling; its pump
    ability is already parser-claimed (`author_card.py reuse`) and just
    copied here verbatim, since registering a card replaces the parser's
    specs wholesale rather than merging with them.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Whenever an opponent activates an ability of an "
                     "artifact, creature, or land that isn't a mana "
                     "ability, this creature deals 1 damage to that "
                     "player.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": 3, "toughness": 3, "keywords": ["menace"]})],
            cost={"text": "{3}{r}{r}"},
            raw_text="{3}{r}{r}: ~ gets +3/+3 and gains menace until end of turn.",
        ),
    ]


register("Immolation Shaman", _immolation_shaman)


def _zo_zu_the_punisher() -> list[AbilitySpec]:
    """Whenever a land enters, Zo-Zu deals 2 damage to that land's
    controller. — Zo-Zu the Punisher. Named-by-proper-noun self-reference
    (not "this creature"/"~"), which `normalize._fold_self_reference`
    doesn't fold for a hyphenated card name — hand-authored rather than
    chasing that edge case for one card. New `DealDamageEffect`
    ``selector="event_controller"`` (the entering land's own controller,
    distinct from ``"event_player"``'s cast/draw-shaped "acting player").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_controller"})],
            trigger={
                "event": "ENTERS_BATTLEFIELD",
                "condition": {"subject": "group", "type": "land"},
            },
            raw_text="Whenever a land enters, Zo-Zu deals 2 damage to "
                     "that land's controller.",
        )
    ]


register("Zo-Zu the Punisher", _zo_zu_the_punisher)


def _spiteful_banditry() -> list[AbilitySpec]:
    """When this enchantment enters, it deals X damage to each creature.
    Whenever one or more creatures your opponents control die, you create
    a Treasure token. This ability triggers only once each turn.

    — Spiteful Banditry. New `DealDamageEffect.x_multiplier` (the
    `AddCountersEffect` primitive's own sibling) for the ETB's announced
    {X}. The "one or more … die" aggregate quantifier is approximated by
    an ordinary per-creature DIES group trigger plus the printed "only
    once each turn" cap (``trigger["limit"]``) — both shapes create at
    most one Treasure per turn regardless of how many opponent creatures
    die simultaneously, so the board outcome is identical either way.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"x_multiplier": 1, "selector": "each_creature"})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="When this enchantment enters, it deals X damage to "
                     "each creature.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature", "controller": "not_you"},
                "limit": True,
            },
            raw_text="Whenever one or more creatures your opponents "
                     "control die, you create a Treasure token. This "
                     "ability triggers only once each turn.",
        ),
    ]


register("Spiteful Banditry", _spiteful_banditry)


def _pyrohemia() -> list[AbilitySpec]:
    """At the beginning of the end step, if no creatures are on the
    battlefield, sacrifice this enchantment.
    {R}: This enchantment deals 1 damage to each creature and each player.

    — Pyrohemia. New `EffectSpec.condition` key ``no_creatures_on_
    battlefield`` (global, unlike the existing controller-scoped
    ``controls_none_of_type``); the activated ability reuses
    `DealDamageEffect`'s already-shipped ``each_creature_and_player``
    selector (Volcanic Fallout-shaped) verbatim — this card's own body just
    hadn't been recognized by the parser yet.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {}, condition={"no_creatures_on_battlefield": True})],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "end"}},
            raw_text="At the beginning of the end step, if no creatures "
                     "are on the battlefield, sacrifice this enchantment.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 1, "selector": "each_creature_and_player"})],
            cost={"text": "{r}"},
            raw_text="{r}: this enchantment deals 1 damage to each "
                     "creature and each player.",
        ),
    ]


register("Pyrohemia", _pyrohemia)


def _karn_the_great_creator() -> list[AbilitySpec]:
    """Activated abilities of artifacts your opponents control can't be
    activated.
    +1: Until your next turn, up to one target noncreature artifact
    becomes an artifact creature with power and toughness each equal to
    its mana value.
    -2: You may reveal an artifact card you own from outside the game or
    choose a face-up artifact card you own in exile. Put that card into
    your hand.

    — Karn, the Great Creator. First static already parser-claimed
    (`activation_prohibition`). The +1 needs two new primitives: RULE
    115.1c's `"noncreature_artifact"` target kind, and `type_change`'s new
    ``pt_selector="mana_value"`` (a dynamic sibling of its existing literal
    ``power``/``toughness`` ints), wrapped in the RULE 611.2b
    `GrantUntilEffect` (``duration="your_next_turn"``) — the same primitive
    "until end of turn" grants use, just a different sweep window. The -2
    is a **documented simplification**: this engine has no "outside the
    game" zone (a sideboard-like concept with no Commander legal use), so
    only its real half — reclaim a face-up artifact card from exile — is
    modeled; the "reveal … from outside the game" branch is dropped.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {
                "affects": "opponents_permanents", "card_type": "artifact",
            })],
            raw_text="Activated abilities of artifacts your opponents "
                     "control can't be activated.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "type_change", "params": {
                    "add_types": ["creature"], "pt_selector": "mana_value",
                }},
                "duration": "your_next_turn",
                "target_kind": "noncreature_artifact",
                "optional": True,
                "count": 1,
            })],
            cost={"loyalty": 1},
            raw_text="+1: Until your next turn, up to one target "
                     "noncreature artifact becomes an artifact creature "
                     "with power and toughness each equal to its mana "
                     "value.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact"}, "destination": "hand", "zones": ["exile"],
            })],
            cost={"loyalty": -2},
            raw_text="-2: Choose a face-up artifact card you own in "
                     "exile. Put that card into your hand.",
        ),
    ]


register("Karn, the Great Creator", _karn_the_great_creator)


def _cemetery_gatekeeper() -> list[AbilitySpec]:
    """First strike
    When this creature enters, exile a card from a graveyard.
    Whenever a player plays a land or casts a spell, if it shares a card
    type with the exiled card, this creature deals 2 damage to that
    player.

    — Cemetery Gatekeeper. ``any_graveyard_card`` is the existing Regrowth/
    Reanimate-family target kind ("a graveyard" — RULE 115's "any single
    graveyard, whosever it is"); `ExileEffect.remember` stamps the exiled
    card's `instance_id` onto `GameObject.linked_exile_id`, and the new
    `EffectSpec.condition` key ``shares_type_with_linked_exile`` (RULE
    205.2a real card types only) gates the two payoff triggers — one per
    firing event (LAND_PLAYED/SPELL_CAST), the same "one spec per event"
    shape the "scry or surveil" compound trigger uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "any_graveyard_card", "remember": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="When this creature enters, exile a card from a "
                     "graveyard.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"},
                        condition={"shares_type_with_linked_exile": True})],
            trigger={"event": "LAND_PLAYED", "condition": {"subject": "group"}},
            raw_text="Whenever a player plays a land, if it shares a card "
                     "type with the exiled card, this creature deals 2 "
                     "damage to that player.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"},
                        condition={"shares_type_with_linked_exile": True})],
            trigger={"event": "SPELL_CAST", "condition": {"subject": "group"}},
            raw_text="Whenever a player casts a spell, if it shares a "
                     "card type with the exiled card, this creature deals "
                     "2 damage to that player.",
        ),
    ]


register("Cemetery Gatekeeper", _cemetery_gatekeeper)


def _ojer_axonil_deepest_might() -> list[AbilitySpec]:
    """Trample
    If a red source you control would deal an amount of noncombat damage
    less than Ojer Axonil's power to an opponent, that source deals
    damage equal to Ojer Axonil's power instead.
    When Ojer Axonil dies, return it to the battlefield tapped and
    transformed under its owner's control.

    — Ojer Axonil, Deepest Might. New replacement `damage_floor_from_
    source_power` — `_additional_damage_replacement`'s floor-shaped
    sibling, reading the live threshold/replacement amount off this same
    source's own current power rather than a flat bonus. The death trigger
    reuses `ReturnSelfFromGraveyardEffect`'s existing ``transformed`` flag
    (also fixing a dormant bug along the way: its ``tapped`` param had
    never actually been applied — see the effect's own docstring).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("damage_floor_from_source_power", {"colors": ["R"]})],
            raw_text="If a red source you control would deal an amount "
                     "of noncombat damage less than Ojer Axonil's power "
                     "to an opponent, that source deals damage equal to "
                     "Ojer Axonil's power instead.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_from_graveyard_untargeted", {
                "destination": "battlefield", "tapped": True, "transformed": True,
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
            raw_text="When Ojer Axonil dies, return it to the "
                     "battlefield tapped and transformed under its "
                     "owner's control.",
        ),
    ]


register("Ojer Axonil, Deepest Might // Temple of Power", _ojer_axonil_deepest_might)


def _powerbalance() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may reveal the top card of
    your library. If you do, you may cast that card without paying its
    mana cost if the two spells have the same mana value.

    — Powerbalance. New `reveal_top_then_free_cast_if_mv_match`; see the
    effect's own docstring for its two "you may" simplifications (the
    reveal is unconditional, the cast stays a genuine choice).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("reveal_top_then_free_cast_if_mv_match", {})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Whenever an opponent casts a spell, you may reveal "
                     "the top card of your library. If you do, you may "
                     "cast that card without paying its mana cost if the "
                     "two spells have the same mana value.",
        )
    ]


register("Powerbalance", _powerbalance)


def _silence() -> list[AbilitySpec]:
    """Your opponents can't cast spells this turn.

    — Silence. The existing `GrantUntilEffect`/`duration="end_of_turn"`
    wrapper around the standing `cast_prohibition` static (scope=
    "opponents") — no target of its own, unlike every other `GrantUntil
    Effect` user so far.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_until", {
                "static": {"type": "cast_prohibition", "params": {"scope": "opponents"}},
                "duration": "end_of_turn",
                "target_kind": None,
            })],
            raw_text="Your opponents can't cast spells this turn.",
        )
    ]


register("Silence", _silence)


def _utopia_sprawl() -> list[AbilitySpec]:
    """Enchant Forest
    As this Aura enters, choose a color.
    Whenever enchanted Forest is tapped for mana, its controller adds an
    additional one mana of the chosen color.

    — Utopia Sprawl. Wild Growth's own triggered-mana-ability shape
    (RULE 605.1b/605.4 — resolves off-stack so the extra mana is there in
    time to spend), just reading `AddManaEffect`'s new `color_from_source_
    chosen_color` flag instead of a fixed `colors` list.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_color_on_enter", {})],
            raw_text="As this Aura enters, choose a color.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {
                "color_from_source_chosen_color": True, "recipient": "event_controller",
            })],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
            raw_text="Whenever enchanted Forest is tapped for mana, its "
                     "controller adds an additional one mana of the "
                     "chosen color.",
        ),
    ]


register("Utopia Sprawl", _utopia_sprawl)


def _senseis_divining_top() -> list[AbilitySpec]:
    """{1}: Look at the top three cards of your library, then put them
    back in any order.
    {T}: Draw a card, then put this artifact on top of its owner's
    library.

    — Sensei's Divining Top. Its first ability is the shared `scry`
    non-interactive resolution (Ponder's own precedent — every legal "any
    order" outcome is already reachable); the second needs
    `ReturnToLibraryEffect`'s new self mode (``target_kind=None``, no
    RULE 115 target at all).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("scry", {"count": 3})],
            cost={"text": "{1}"},
            raw_text="{1}: Look at the top three cards of your library, "
                     "then put them back in any order.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("return_to_library", {"target_kind": None, "position": "top"}),
            ],
            cost={"taps_self": True},
            raw_text="{T}: Draw a card, then put this artifact on top of "
                     "its owner's library.",
        ),
    ]


register("Sensei's Divining Top", _senseis_divining_top)


