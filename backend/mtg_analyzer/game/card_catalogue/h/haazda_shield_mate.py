from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _haazda_shield_mate() -> list[AbilitySpec]:
    """At the beginning of your upkeep, sacrifice this creature unless you
    pay {W}{W}.
    {W}: The next time a source of your choice would deal damage to you
    this turn, prevent that damage.

    — The upkeep clause is the general RULE 701.17 ``sacrifice_unless_pay``
    interactive pay-or-lose-it choice (already shipped for Arcades Sabboth/
    Breeding Pit/Child of Gaea); registering this card for its own
    prevent-damage clause (still `UNMODELED` by the parser) would otherwise
    silently drop the upkeep clause too — `specs_for` trusts a registered
    card's specs wholesale — so it's authored alongside rather than left
    to the parser it can no longer reach.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_unless_pay", {"cost": "{W}{W}"})],
            trigger={
                "event": "STEP_BEGIN", "filter": {"step": "upkeep"},
                "phase_relation": "you",
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"mana": "{W}"},
        ),
    ]


register("Haazda Shield Mate", _haazda_shield_mate)
