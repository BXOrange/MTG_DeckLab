from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _honor_the_fallen() -> list[AbilitySpec]:
    """Exile all creature cards from all graveyards. You gain 1 life for each card exiled this way.

    — PLAY-ALL (Hope to the last). Crypt Incursion's shape: `exile_all_graveyards` narrowed by ``card_type`` (new), then a
    `bind` measuring ``objects_exiled_this_way`` into `gain_life`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "exile_all_graveyards", "params": {"card_type": "creature"}},
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "this_way", "tally": "objects_exiled_this_way"},
                    "effects": [{"type": "gain_life", "params": {"amount": "$n"}}],
                }},
            ]})],
        ),
    ]


register("Honor the Fallen", _honor_the_fallen)
