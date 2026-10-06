from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "each of up to three target creatures".
_MAX_TARGETS = 3


def _protection_magic() -> list[AbilitySpec]:
    """Put a shield counter on each of up to three target creatures. (If a creature with a shield counter would be dealt damage or destroyed, remove a shield counter from it instead.)

    — PLAY-ALL (Hope to the last). The multi-target `add_counters` shape (one counter per target, 0–3 targets) with the
    engine's existing ``shield`` counter kind (RULE 122.1c).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "shield", "target_kind": "creature", "target_count": _MAX_TARGETS,
                "optional": True,
            })],
        ),
    ]


register("Protection Magic", _protection_magic)
