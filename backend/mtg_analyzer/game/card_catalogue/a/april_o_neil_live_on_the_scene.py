from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _april_o_neil_live_on_the_scene() -> list[AbilitySpec]:
    """Whenever a Mutant, Ninja, or Turtle you control enters, investigate. (Create a Clue token. It's an artifact with "{2}, Sacrifice this token: Draw a card.")
    Partner—Character select

    — PLAY-ALL (Turtle Power!). Partner is a keyword. A group enters trigger whose filter is an ``any_of`` over the three creature subtypes (April herself is a Human Detective, so she does not trigger it) over a Clue `create_token`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Clue"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False,
                "filter": {"any_of": [{"subtype": "mutant"}, {"subtype": "ninja"}, {"subtype": "turtle"}]},
            }},
        ),
    ]


register("April O'Neil, Live on the Scene", _april_o_neil_live_on_the_scene)
