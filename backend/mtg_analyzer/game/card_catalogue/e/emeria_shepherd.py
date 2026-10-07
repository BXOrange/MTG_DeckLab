from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _emeria_shepherd() -> list[AbilitySpec]:
    """Flying
    Landfall — Whenever a land you control enters, you may return target nonland permanent card from your graveyard to your hand. If that land is a Plains, you may return that nonland permanent card to the battlefield instead.

    Targets are announced with the landfall trigger. A Plains offers the
    battlefield alternative at resolution; declining that alternative returns
    the selected card to hand. The controller can also decline the whole return.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("if_else", {
                "condition": {"kind": "is_subtype", "of": "trigger_subject", "subtype": "plains"},
                "then": [{"type": "optional", "params": {
                    "prompt": "Emeria Shepherd: Karte stattdessen ins Spiel zurückbringen? (Nein: auf die Hand)",
                    "effects": [{"type": "return_from_graveyard", "params": {
                        "target_kind": "graveyard_nonland_permanent", "destination": "battlefield",
                    }}],
                    "else_effects": [{"type": "return_from_graveyard", "params": {
                        "target_kind": "graveyard_nonland_permanent", "destination": "hand",
                    }}],
                }}],
                "else": [{"type": "return_from_graveyard", "params": {
                    "target_kind": "graveyard_nonland_permanent", "destination": "hand",
                }}],
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
            },
            optional=True,
        ),
    ]


register("Emeria Shepherd", _emeria_shepherd)
