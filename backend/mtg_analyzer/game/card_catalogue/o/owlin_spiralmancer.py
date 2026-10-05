from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _owlin_spiralmancer() -> list[AbilitySpec]:
    """Flying, vigilance
    Whenever you cast your first spell with {X} in its mana cost each turn,
    you may copy it. You may choose new targets for the copy."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_spell", {"spell_from_trigger_event": "instance_id"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "first_x_spell": True,
            },
            optional=True,
        ),
    ]


register("Owlin Spiralmancer", _owlin_spiralmancer)
