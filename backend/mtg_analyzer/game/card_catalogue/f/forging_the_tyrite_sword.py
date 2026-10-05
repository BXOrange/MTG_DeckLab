from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _forging_the_tyrite_sword() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter.
    Sacrifice after III.)
    I, II — Create a Treasure token.
    III — Search your library for a card named Halvar, God of Battle or an
    Equipment card, reveal it, put it into your hand, then shuffle.

    — Forging the Tyrite Sword. Chapter III drops the "named Halvar, God of
    Battle" alternative (a name-*or*-type search the ``search`` effect's
    criteria can't express — it can only AND conditions, not OR two
    different shapes) and always searches for an Equipment card instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1, 2]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "Equipment"}, "destination": "hand"})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
        ),
    ]


register("Forging the Tyrite Sword", _forging_the_tyrite_sword)
