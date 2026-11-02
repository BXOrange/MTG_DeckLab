from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sewers_of_estark() -> list[AbilitySpec]:
    """Choose target creature. If it's attacking, it can't be blocked this turn. If it's blocking, prevent all combat damage that would be dealt this combat by it and each creature it's blocking.

    One RULE 115 announcement serves both branches: the attacking branch carries the target, the blocking branch has no
    `target_spec` of its own and reads the sibling's target (`ConditionalEffect`). RULE 506.4 / 509.1: the branch is the
    target's combat role, ``source_attacking`` / ``source_blocking`` with ``of: "target"``. The prevention is
    `prevent_combat_damage_by_blocker_and_blocked` (RULE 615, dealt-by only, so damage *to* them still happens).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("unblockable", {"target_kind": "creature"},
                           condition={"kind": "source_attacking", "of": "target"}),
                EffectSpec("prevent_combat_damage_by_blocker_and_blocked", {},
                           condition={"kind": "source_blocking", "of": "target"}),
            ],
        ),
    ]


register("Sewers of Estark", _sewers_of_estark)
