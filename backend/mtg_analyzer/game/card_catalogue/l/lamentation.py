from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lamentation() -> list[AbilitySpec]:
    """When this creature enters, destroy target creature an opponent controls.
    You gain 3 life.
    Encore {6}{B}{B}

    A singleton precon creature: the engine already composes one targeted
    destruction with a following untargeted life gain, and the existing
    Encore keyword binding supplies its graveyard activated ability.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("destroy", {"target_kind": "creature_you_dont_control"}),
                EffectSpec("gain_life", {"amount": 3}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Lamentation", _lamentation)
