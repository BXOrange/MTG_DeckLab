from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _yasharn_implacable_earth() -> list[AbilitySpec]:
    """Yasharn, Implacable Earth (Legendary Creature — Elemental Boar,
    {2}{G}{W})

    "When Yasharn enters, search your library for a basic Forest card and
    a basic Plains card, reveal those cards, put them into your hand, then
    shuffle.
    Players can't pay life or sacrifice nonland permanents to cast spells
    or activate abilities."

    The ETB is two independent single-card searches (a Forest, then a
    Plains — `SearchLibraryEffect` has no "two distinct named basics in
    one search" shape, but running it twice with different criteria is
    rules-equivalent and simpler). The restriction reuses the new
    ``cost_restriction`` static (MEC-40), checked at every cost-payment
    choke point that offers a pay-life/sacrifice component.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("search", {"criteria": {"basic": True, "type": "Forest"}, "destination": "hand"}),
                EffectSpec("search", {"criteria": {"basic": True, "type": "Plains"}, "destination": "hand"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_restriction", {"kinds": ["pay_life", "sacrifice_nonland_permanent"]})],
        ),
    ]


register("Yasharn, Implacable Earth", _yasharn_implacable_earth)
