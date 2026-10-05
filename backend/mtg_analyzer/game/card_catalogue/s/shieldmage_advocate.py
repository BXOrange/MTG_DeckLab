from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shieldmage_advocate() -> list[AbilitySpec]:
    """{T}: Return target card from an opponent's graveyard to their hand.
    Prevent all damage that would be dealt to any target this turn by a
    source of your choice.

    — One activated ability, two independent effects: an ordinary
    ``"return_to_hand"`` targeting an opponent's graveyard card, then
    Circle of Despair's own ``target_kind="any"`` chooser shield.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("return_to_hand", {"target_kind": "opponent_graveyard_card"}),
                EffectSpec("request_prevent_damage_source", {"target_kind": "any", "amount": "all"}),
            ],
            cost={"taps_self": True},
        ),
    ]


register("Shieldmage Advocate", _shieldmage_advocate)
