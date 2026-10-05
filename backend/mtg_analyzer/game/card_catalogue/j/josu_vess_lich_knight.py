from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _josu_vess_lich_knight() -> list[AbilitySpec]:
    """Kicker {5}{B}
    Menace
    When Josu Vess enters, if he was kicked, create eight 2/2 black Zombie Knight creature tokens with menace.

    — PLAY-ALL Step 2 (Wretched Ranks). Kicker and menace are printed keywords. The enter trigger's "if he was
    kicked" is the same ``kicked`` condition the parser attaches to "if it was kicked".
    """
    return [AbilitySpec(
        "triggered",
        [EffectSpec("create_token", {
            "count": 8, "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Zombie", "Knight"],
            "keywords": ["menace"], "token_name": "Zombie Knight",
        }, condition={"kind": "kicked", "min": 1})],
        trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
    )]


register("Josu Vess, Lich Knight", _josu_vess_lich_knight)
