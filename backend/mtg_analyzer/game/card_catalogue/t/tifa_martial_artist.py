from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tifa_martial_artist() -> list[AbilitySpec]:
    """Melee (Whenever this creature attacks, it gets +1/+1 until end of
    turn for each opponent you attacked this combat.)
    Whenever one or more creatures you control with power 7 or greater deal
    combat damage to a player, untap all creatures you control. If it's the
    first combat phase of your turn, there is an additional combat phase
    after this phase.

    MEC-29: the other half of MEC-28's own five-card list, closed by
    building the two primitives its own diagnosis named — though the
    diagnosis itself needed correcting first (this repo's standing rule:
    verify a "needs a new primitive" claim against current code before
    trusting it, even when the claim is this ticket's own). RULE 603.1's
    DAMAGE-subject group scoping for "you control" already existed
    (`_GROUP_CONTROLLER_EVENT_KEYS["DAMAGE"]`, built for Bident of Thassa/
    Deepfathom Skulker's own "a creature you control deals combat damage to
    a player") — the real, still-open gap was the **"one or more"**
    quantifier: RULE 603.1's ordinary group subject fires once *per
    creature*, but "one or more creatures … deal combat damage" describes a
    single condition about the whole combat damage step. This engine
    already has the identical shape solved once, for a different verb: RULE
    506.4's "a player attacks you **with one or more creatures**" is
    exactly why `EventType.PLAYER_ATTACKED` exists instead of reusing the
    per-declaration `ATTACKS` event (see that event's own docstring) — two
    creatures qualifying simultaneously must trigger this ability *once*,
    not twice (this card's own payoff, an extra combat phase, would
    otherwise double up per RULE 508.6/509.5's simultaneous combat damage).
    Built the combat-damage sibling the same way:
    `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`
    (`GameEngine._apply_combat_damage`), fired once per (contributing
    creatures' controller, player hit) pair after a damage step, carrying
    ``max_power`` — the highest power among that pair's contributors — for
    a new `"contributor_power_at_least"` trigger-condition threshold
    (`effect_binder._trigger_condition`, mirroring the existing
    ``spell_mana_value_at_most`` idiom) to check: the aggregate event names
    no single acting object a `"group"` condition's own per-object
    ``min_power`` filter could read off the board.

    Hand-authored rather than left to the oracle-text parser: this
    "one or more `<type>` you control with power `<n>` or greater deal
    combat damage to a player" template is, per `parser_probe.py cards
    'deal combat damage to a player'`, printed on exactly this one cached
    card — not worth a dedicated grammar row for a single user. "If it's
    the first combat phase of **your** turn" (not "…of **the** turn",
    `_FIRST_COMBAT_PHASE_CONDITION_RE`'s own exact wording) rides the same
    RULE 603.4 intervening-if `ConditionalEffect` key
    (``is_first_combat_phase``) under a harmless wording variant: a combat
    phase only ever happens on its own active player's turn, so "the turn"
    and "your turn" name the same thing for every real card printing
    either.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {"selector": "creatures_you_control", "untap": True}),
                EffectSpec("extra_combat_phase", {}, condition={"is_first_combat_phase": True}),
            ],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "you"},
                "contributor_power_at_least": 7,
            },
        ),
    ]


register("Tifa, Martial Artist", _tifa_martial_artist)
