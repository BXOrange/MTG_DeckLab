from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The parser's "any number of target …" cap (`_ANY_NUMBER_TARGET_CAP`).
_ANY_NUMBER = 10


def _clever_concealment() -> list[AbilitySpec]:
    """Convoke (Your creatures can help cast this spell. Each creature you tap while casting this spell pays for {1} or one mana of that creature's color.)
    Any number of target nonland permanents you control phase out. (Treat them and anything attached to them as though they don't exist until your next turn.)

    — PLAY-ALL (Limit Break). Convoke is the keyword. `phase_out` over up to ten nonland permanents you control (Guardian of Faith's "any number" cap).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("phase_out", {"target_kind": "nonland_permanent_you_control", "count": _ANY_NUMBER, "optional": True})],
        ),
    ]


register("Clever Concealment", _clever_concealment)
