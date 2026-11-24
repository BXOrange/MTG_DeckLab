from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lord_of_the_undead() -> list[AbilitySpec]:
    """Other Zombie creatures get +1/+1.
    {1}{B}, {T}: Return target Zombie card from your graveyard to your hand.

    — PLAY-ALL Step 2 (Wretched Ranks). The anthem is the parser's own claim (every other Zombie, any controller);
    the activation is Morcant's Loyalist's subtype-scoped `return_from_graveyard`.
    """
    return [
        AbilitySpec("static", [EffectSpec("anthem", {
            "power": 1, "toughness": 1, "affects": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature", "subtype": "Zombie", "not_reference": True}},
        })]),
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "subtype": "zombie", "destination": "hand",
            })],
            cost={"mana": "{1}{B}", "taps_self": True},
        ),
    ]


register("Lord of the Undead", _lord_of_the_undead)
