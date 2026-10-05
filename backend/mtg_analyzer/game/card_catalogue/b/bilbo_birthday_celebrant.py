from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bilbo_birthday_celebrant() -> list[AbilitySpec]:
    """If you would gain life, you gain that much life plus 1 instead.
    {2}{W}{B}{G}, {T}, Exile Bilbo: Search your library for any number of
    creature cards, put them onto the battlefield, then shuffle. Activate
    only if you have 111 or more life.

    Simplified: the lifegain-plus-1 replacement and the "111 or more
    life" activation gate aren't modeled (no lifegain-amount replacement/
    activation-condition primitive reaches this exact shape yet); the
    exile-self cost is approximated as sacrifice-self (no battlefield
    "exile this permanent as a cost" primitive exists — only a hand-zone
    one). The tutor-and-mass-reanimate itself is fully modeled.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"}, "destination": "battlefield",
                "count": 99, "optional": True,
            })],
            cost={"mana": "{2}{W}{B}{G}", "taps_self": True, "sacrifice": "self"},
        ),
    ]


register("Bilbo, Birthday Celebrant", _bilbo_birthday_celebrant)
