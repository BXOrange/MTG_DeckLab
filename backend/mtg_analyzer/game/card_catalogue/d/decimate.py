from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _decimate() -> list[AbilitySpec]:
    """Destroy target artifact, target creature, target enchantment, and target land. (You can't
    cast this spell unless you have legal choices for all its targets.)

    — Animated Army deck batch. Four `destroy` effects, each announcing its own target (RULE 601.2c),
    the same one-target-per-effect shape as any multi-target spell.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("destroy", {"target_kind": "artifact"}),
            EffectSpec("destroy", {"target_kind": "creature"}),
            EffectSpec("destroy", {"target_kind": "enchantment"}),
            EffectSpec("destroy", {"target_kind": "land"}),
        ]),
    ]


register("Decimate", _decimate)
