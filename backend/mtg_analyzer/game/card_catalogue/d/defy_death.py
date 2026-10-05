from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "put two +1/+1 counters on it" for an Angel.
_ANGEL_COUNTERS = 2


def _defy_death() -> list[AbilitySpec]:
    """Return target creature card from your graveyard to the battlefield. If it's an Angel, put two +1/+1 counters on it.

    — PLAY-ALL (Calling All Angels). The reanimation, then `add_counters` over ``previous_subject`` ("it") gated by
    ``previous_target_has_subtype: Angel`` (Essence Flux's idiom).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {"target_kind": "graveyard_creature", "destination": "battlefield"}),
                EffectSpec(
                    "add_counters", {"count": _ANGEL_COUNTERS, "kind": "+1/+1", "previous_subject": True},
                    condition={"previous_target_has_subtype": "Angel"},
                ),
            ],
        ),
    ]


register("Defy Death", _defy_death)
