from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _georgiou_terran_emperor() -> list[AbilitySpec]:
    """You don't lose the game for having 0 or less life.
    At the beginning of your end step, you lose 3 life and draw a card. Then if your life total is 0 or less, create ten 1/1 red Officer creature tokens.
    """
    return [
        AbilitySpec("static", [EffectSpec("cant_lose_game", {"reason": "life"})]),
        AbilitySpec("triggered", [
            EffectSpec("lose_life", {"amount": 3}),
            EffectSpec("draw", {"count": 1}),
            EffectSpec("create_token", {"count": 10, "power": 1, "toughness": 1,
                "colors": ["R"], "subtypes": ["Officer"], "token_name": "Officer"},
                condition={"kind": "life_at_most", "amount": 0}),
        ], trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"}),
    ]


register("Georgiou, Terran Emperor", _georgiou_terran_emperor)
