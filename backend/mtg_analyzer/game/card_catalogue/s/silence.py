from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _silence() -> list[AbilitySpec]:
    """Your opponents can't cast spells this turn.

    — Silence. The existing `GrantUntilEffect`/`duration="end_of_turn"`
    wrapper around the standing `cast_prohibition` static (scope=
    "opponents") — no target of its own, unlike every other `GrantUntil
    Effect` user so far.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_until", {
                "static": {"type": "cast_prohibition", "params": {"scope": "opponents"}},
                "duration": "end_of_turn",
                "target_kind": None,
            })],
        )
    ]


register("Silence", _silence)
