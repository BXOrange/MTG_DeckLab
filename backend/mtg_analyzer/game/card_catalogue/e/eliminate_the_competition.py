from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eliminate_the_competition() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice X creatures.
    Destroy X target creatures.

    — Eliminate the Competition. Immoral Bargain's `immoral_bargain` effect with ``destroy_kind="creature"``:
    X is the number of creatures sacrificed, then that many creatures are chosen and destroyed. Shares its
    documented simplification — the sacrifice and the choice of X creatures are made at resolution rather than
    as an announced cost and targets.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("immoral_bargain", {"destroy_kind": "creature"})],
        ),
    ]


register("Eliminate the Competition", _eliminate_the_competition)
