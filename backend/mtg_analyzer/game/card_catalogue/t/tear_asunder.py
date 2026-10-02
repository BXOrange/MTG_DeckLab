from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tear_asunder() -> list[AbilitySpec]:
    """Kicker {1}{B} (You may pay an additional {1}{B} as you cast this spell.)
    Exile target artifact or enchantment. If this spell was kicked, exile target
    nonland permanent instead.

    — PLAY-ALL Step 2 (World Shaper). Kicker is the keyword fold-in. The target
    switch is the new `TargetSpec.kind_if_flag` (``{flag: kicked, kind:
    nonland_permanent}`` — through `ExileEffect`'s ``kind_if_flag`` param): kicker
    is paid before targets are chosen, so which *kind* of permanent is legal is
    already decided when targets are offered. `unless_flag` could not do this (it
    only drops narrowing filters, never changes the kind), and an `if_else` cannot
    announce targets.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile", {
                "target_kind": "artifact_or_enchantment",
                "kind_if_flag": {"flag": "kicked", "kind": "nonland_permanent"},
            })],
        ),
    ]


register("Tear Asunder", _tear_asunder)
