from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _awe_strike() -> list[AbilitySpec]:
    """The next time target creature would deal damage this turn, prevent
    that damage. You gain life equal to the damage prevented this way.

    — `PreventDamageFromTargetEffect`'s own targeted, no-chooser-needed
    shape (Dazzling Reflection's own life-gain half is a separate,
    not-yet-built "gain life equal to a target's power" primitive — left
    open, see `BACKLOG.md`'s `MEC-30`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("prevent_damage_from_target", {
                "target_kind": "creature",
                "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you"},
            })],
        ),
    ]


register("Awe Strike", _awe_strike)
