from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cleaver_skaab() -> list[AbilitySpec]:
    """{3}, {T}, Sacrifice another Zombie: Create two tokens that are copies of the sacrificed creature.

    The cost is the plain activation-cost grammar ("Sacrifice another Zombie" is excluded from paying with the
    Skaab itself, RULE 109.5). The effect is the new `copy_sacrificed` (`effects/copy_sacrificed.py`): the
    sacrifice cost stamps the victim's copiable card on this source (`note_sacrificed`), and two token copies are
    made from it (RULE 707.2).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("copy_sacrificed", {"count": 2})],
            cost={"text": "{3}, {T}, Sacrifice another Zombie"},
        ),
    ]


register("Cleaver Skaab", _cleaver_skaab)
