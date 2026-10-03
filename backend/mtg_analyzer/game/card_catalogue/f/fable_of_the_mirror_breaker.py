from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fable_of_the_mirror_breaker() -> list[AbilitySpec]:
    """I — Create a 2/2 red Goblin Shaman creature token with "Whenever this
    token attacks, create a Treasure token."
    II — You may discard up to two cards. If you do, draw that many cards.
    III — Exile this Saga, then return it to the battlefield transformed under
    your control.
    """
    return [
        AbilitySpec("triggered", [EffectSpec("create_token", {
            "token_name": "Goblin Shaman", "count": 1, "power": 2, "toughness": 2,
            "colors": ["R"], "subtypes": ["Goblin", "Shaman"],
            "oracle_text": "Whenever this token attacks, create a Treasure token.",
        })], trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]}),
        AbilitySpec("triggered", [EffectSpec("discard", {
            "count_max": 2, "then_draw_discarded": True,
        })], trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2]}),
        AbilitySpec("triggered", [EffectSpec("exile_return_transformed", {})],
                    trigger={"event": EventType.SAGA_CHAPTER, "chapter": [3]}),
    ]


register("Fable of the Mirror-Breaker", _fable_of_the_mirror_breaker)
register("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", _fable_of_the_mirror_breaker)
