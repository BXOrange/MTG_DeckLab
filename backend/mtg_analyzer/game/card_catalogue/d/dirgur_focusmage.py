from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dirgur_focusmage() -> list[AbilitySpec]:
    """Instant and sorcery spells you cast cost {1} less to cast.
    Whenever you cast an instant or sorcery spell with mana value 5 or
    greater from your hand, this creature becomes prepared."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "your_spells", "generic": 1, "spell_type": ["instant", "sorcery"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
                "spell_mana_value_at_least": 5,
                "filter": {"from_hand": True},
            },
        ),
    ]


register("Dirgur Focusmage", _dirgur_focusmage)
register("Dirgur Focusmage // Braingeyser", _dirgur_focusmage)
