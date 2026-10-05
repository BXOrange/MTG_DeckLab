from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _virtual_assistant() -> list[AbilitySpec]:
    """Defender
    Whenever you cast a spell using teamwork, create a 1/1 colorless Robot
    Hero artifact creature token with flying.

    — PAR-68. Defender is a plain printed keyword. The trigger is the new
    `requires_spell_cast_via_teamwork` predicate — the ordinary "whenever
    you cast a spell" `SPELL_CAST` shape, narrowed by reading the just-cast
    spell's own `GameObject.teamwork_paid` flag straight off the event's
    `instance_id` (no new event field needed, unlike Agent Maria Hill's own
    TAPPED-event case).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Robot Hero", "power": 1, "toughness": 1,
                "colors": [], "is_artifact": True,
                "subtypes": ["Robot", "Hero"], "keywords": ["Flying"],
            })],
            trigger={
                "event": "SPELL_CAST", "condition": {"subject": "you"},
                "requires_spell_cast_via_teamwork": True,
            },
        ),
    ]


register("Virtual Assistant", _virtual_assistant)
