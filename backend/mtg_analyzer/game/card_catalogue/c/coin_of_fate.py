from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _coin_of_fate() -> list[AbilitySpec]:
    """When this artifact enters, surveil 1.
    {3}{W}, {T}, Exile two creature cards from your graveyard, Sacrifice this artifact: An opponent chooses one of the exiled cards. You put that card on the bottom of your library and return the other to the battlefield tapped. You become the monarch.

    — PLAY-ALL (Revival Trance). The surveil is the parser's. The cost is mana, tap, ``exile 2 creature cards from your
    graveyard`` (their ids are kept on the source, `last_cost_exiled_ids`) and a self-sacrifice; the effect is the new
    `coin_of_fate_split`. **Simplification:** the opponent's choice is made as the one worst for you — the more expensive
    card goes to the bottom, the cheaper one returns.
    """
    return [
        AbilitySpec(
            "triggered", [EffectSpec("surveil", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("coin_of_fate_split", {})],
            cost={"text": "{3}{w}, {t}, exile two creature cards from your graveyard, sacrifice ~"},
        ),
    ]


register("Coin of Fate", _coin_of_fate)
