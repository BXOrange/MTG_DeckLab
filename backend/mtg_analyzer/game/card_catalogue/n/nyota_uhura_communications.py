from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nyota_uhura_communications() -> list[AbilitySpec]:
    """Hailing Frequencies — As Nyota Uhura enters, choose a number between 0 and 10.
    Open a Channel — Whenever an opponent casts a spell with mana value equal to the chosen number, you draw a card.
    """
    return [
        AbilitySpec("enter_replacement", [EffectSpec("choose_number_on_enter", {"minimum": 0, "maximum": 10})]),
        AbilitySpec("triggered", [EffectSpec("draw", {"count": 1})], trigger={
            "event": EventType.SPELL_CAST,
            "condition": {"subject": "group", "controller": "not_you"},
            "spell_mana_value_equals_chosen_number": True,
        }),
    ]


register("Nyota Uhura, Communications", _nyota_uhura_communications)
