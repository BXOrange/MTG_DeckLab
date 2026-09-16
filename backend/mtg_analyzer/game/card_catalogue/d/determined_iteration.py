from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _determined_iteration() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, populate. The token created
    this way gains haste. Sacrifice it at the beginning of the next end step.

    Documented simplification: "gains haste" is not modeled — the populated
    copy is sacrificed at the next end step regardless, and it copies an
    existing token whose keywords (often haste already) it inherits."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("populate", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you"},
        ),
    ]


register("Determined Iteration", _determined_iteration)
