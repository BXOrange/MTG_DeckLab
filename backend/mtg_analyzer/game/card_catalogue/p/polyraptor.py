from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _polyraptor() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, create a token
    that's a copy of this creature.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {"target_kind": None})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
        ),
    ]


register("Polyraptor", _polyraptor)
