from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _emeria_shepherd() -> list[AbilitySpec]:
    """Flying
    Landfall — Whenever a land you control enters, you may return target nonland permanent card from your graveyard to your hand. If that land is a Plains, you may return that nonland permanent card to the battlefield instead.

    — PLAY-ALL (Calling All Angels). An optional landfall trigger over a targeted `return_from_graveyard` to hand whose
    ``destination_if`` (Stitch Together's swap) sends it to the battlefield when the entering land (``trigger_subject``) is a
    Plains. **Simplification:** the "instead" is taken whenever it is available, since the battlefield is never worse
    than the hand.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_nonland_permanent", "destination": "hand",
                "destination_if": {
                    "condition": {"kind": "is_subtype", "of": "trigger_subject", "subtype": "plains"},
                    "destination": "battlefield",
                },
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
            },
            optional=True,
        ),
    ]


register("Emeria Shepherd", _emeria_shepherd)
