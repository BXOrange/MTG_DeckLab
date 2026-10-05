from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _essence_flux() -> list[AbilitySpec]:
    """Exile target creature you control, then return that card to the
    battlefield under its owner's control. If it's a Spirit, put a +1/+1
    counter on it.

    — PLAY-ALL Step 2 (Wick Snail Boom). Ephemerate's `blink`, then
    `add_counters` over ``previous_subject`` ("it") gated by
    ``previous_target_has_subtype: Spirit``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("blink", {"target_kind": "creature_you_control"}),
                EffectSpec(
                    "add_counters", {"count": 1, "kind": "+1/+1", "previous_subject": True},
                    condition={"previous_target_has_subtype": "Spirit"},
                ),
            ],
        )
    ]


register("Essence Flux", _essence_flux)
