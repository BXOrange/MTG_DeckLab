from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eumidian_wastewaker() -> list[AbilitySpec]:
    """Collect both players' choices, discard/sacrifice, count land cards.
    Encore is bound by the existing keyword catalogue.
    """
    return [AbilitySpec("triggered", [EffectSpec("choose_player_objects", {
        "then_that_many": {"card_type": "land", "effects": [
            {"type": "draw", "params": {"count": "x"}},
        ]},
    })], trigger={"event": "ATTACKS", "condition": {"subject": "self"}})]


register("Eumidian Wastewaker", _eumidian_wastewaker)
