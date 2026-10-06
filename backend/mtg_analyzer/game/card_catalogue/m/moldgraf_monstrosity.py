from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The printed "two creature cards".
_RETURN_COUNT = 2


def _moldgraf_monstrosity() -> list[AbilitySpec]:
    """Trample
    When this creature dies, exile it, then return two creature cards at random from your graveyard to the battlefield.

    — PLAY-ALL (Death Toll). Trample is a keyword. The dies trigger exiles the Monstrosity first (so it can't be drawn) and then
    `return_from_graveyard`'s ``at_random`` mode returns two creature cards drawn at random (RULE 706) from your graveyard.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile", {"target_kind": None}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "at_random": _RETURN_COUNT, "destination": "battlefield",
                }),
            ],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Moldgraf Monstrosity", _moldgraf_monstrosity)
