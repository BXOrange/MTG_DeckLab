from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vexing_shusher() -> list[AbilitySpec]:
    """Vexing Shusher (Creature — Goblin Shaman, {1}{R})

    "This spell can't be countered.
    {R/G}: Target spell can't be countered."

    The static is already parser-claimable as-is; hand-authored only for
    the activated ability, which is `MarkCantBeCounteredEffect`'s existing
    resolve-time marker (built for Mistrise Village's untargeted "next
    spell you cast") widened with a real `target_kind="spell"` RULE 115
    target instead.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("mark_cant_be_countered", {"target_kind": "spell"})],
            cost={"text": "{R/G}"},
        ),
    ]


register("Vexing Shusher", _vexing_shusher)
