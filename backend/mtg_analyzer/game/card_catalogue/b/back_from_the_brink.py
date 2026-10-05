from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _back_from_the_brink() -> list[AbilitySpec]:
    """Exile a creature card from your graveyard and pay its mana cost:
    Create a token that's a copy of that card. Activate only as a sorcery.

    — MEC-52. The cost is a *pick-then-price* one — a variable mana cost
    unknowable until the graveyard card is chosen — which `game/costs.py`
    and the activation flow have no primitive for. Modeled as the
    resolution of an otherwise-free, ``sorcery_speed_only`` activated
    ability (`BackFromTheBrinkEffect`): on resolution the controller picks
    a creature card in their graveyard and exiles it (seeding the RULE
    608.2 referent), then `PayCostThenPreviousMvEffect` prices "pay its
    mana cost" off that card and, if paid, `copy_permanent`
    ``referent="previous"`` makes the token. See the effect's docstring for
    the (exile-and-payment-at-resolution) simplification.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("back_from_the_brink", {})],
            cost={"sorcery_speed_only": True},
        ),
    ]


register("Back from the Brink", _back_from_the_brink)
