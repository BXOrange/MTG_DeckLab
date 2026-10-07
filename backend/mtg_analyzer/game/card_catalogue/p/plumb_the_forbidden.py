from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _plumb_the_forbidden() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may sacrifice one or
    more creatures. When you do, copy this spell for each creature
    sacrificed this way. You draw a card and lose 1 life."""
    return [
        AbilitySpec("spell_effect", [EffectSpec("draw", {"count": 1}), EffectSpec("lose_life", {"amount": 1})],
                    additional_cost={"sacrifice_count": [-2, "creature"]}, additional_cost_optional=True),
        AbilitySpec("triggered", [EffectSpec("copy_spell", {
            "spell_from_trigger_event": "instance_id", "count_from_trigger_event": "sacrificed_count",
            "choose_new_targets": False,
        })], trigger={"event": "CAST_COST_PAID", "condition": {"subject": "self"}}),
    ]


register("Plumb the Forbidden", _plumb_the_forbidden)
