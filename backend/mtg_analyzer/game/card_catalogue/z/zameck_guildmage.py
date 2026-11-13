
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _zameck_guildmage() -> list[AbilitySpec]:
    '{G}{U}: This turn, each creature you control enters with an additional +1/+1 counter on it.\n{G}{U}, Remove a +1/+1 counter from a creature you control: Draw a card.'
    return [
        AbilitySpec("activated", [EffectSpec("grant_until", {
            "duration": "end_of_turn", "target_kind": None,
            "static": {"type": "extra_etb_counter", "params": {"count": 1, "kind": "+1/+1", "filter": {"card_type": "creature"}, "other": False}},
        })], cost={"mana": "{G}{U}"}),
        AbilitySpec("activated", [EffectSpec("draw", {"count": 1})],
            cost={"text": "{G}{U}, remove a +1/+1 counter from a creature you control"}),
    ]



register('Zameck Guildmage', _zameck_guildmage)
