from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _secret_of_bloodbending() -> list[AbilitySpec]:
    """You control target opponent during their next combat phase. If this
    spell's additional cost was paid, you control that player during their
    next turn instead.

    — MEC-51 (RULE 720), same `control_player` primitive as Mindslaver
    (`card_catalogue/m/mindslaver.py`), here ``scope="combat"``. The
    "if this spell's additional cost was paid (waterbend {10}), you control
    that player during their next turn instead" upgrade is a documented
    card-specific simplification — waterbend additional-cost conditionals
    are their own unmodeled mechanism (`BACKLOG.md`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("control_player", {"scope": "combat", "target_kind": "opponent"}),
                EffectSpec("exile", {"target_kind": None}),
            ],
        ),
    ]


register("Secret of Bloodbending", _secret_of_bloodbending)
