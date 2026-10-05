from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _guardian_project() -> list[AbilitySpec]:
    """Guardian Project (Enchantment, {3}{G})

    "Whenever a nontoken creature you control enters, if it doesn't have
    the same name as another creature you control or a creature card in
    your graveyard, draw a card."

    The RULE 603.1 group-subject trigger condition ("a nontoken creature
    you control enters") is already-general segmenter vocabulary. The
    "if it doesn't have the same name as…" gate is the new
    ``entering_object_unique_name`` `EffectSpec.condition` key (MEC-40).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "draw", {"count": 1},
                    condition={"entering_object_unique_name": True},
                )
            ],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "type": "creature"},
            },
        ),
    ]


register("Guardian Project", _guardian_project)
