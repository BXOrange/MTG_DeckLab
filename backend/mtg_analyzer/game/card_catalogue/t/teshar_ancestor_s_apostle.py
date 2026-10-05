from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _teshar_ancestors_apostle() -> list[AbilitySpec]:
    """Flying
    Whenever you cast a historic spell, return target creature card with mana
    value 3 or less from your graveyard to the battlefield. (Artifacts,
    legendaries, and Sagas are historic.)"""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "battlefield",
                "max_mana_value": 3,
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_is_historic": True,
            },
        ),
    ]


register("Teshar, Ancestor's Apostle", _teshar_ancestors_apostle)
