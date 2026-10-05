from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mutilate() -> list[AbilitySpec]:
    """All creatures get -1/-1 until end of turn for each Swamp you control.

    — PLAY-ALL Step 2 (Wretched Ranks). A `bind` measuring the Swamps you control (negated by ``multiply: -1``) into
    a group `pump` over every creature; the count is taken once, as the spell resolves.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("bind", {
        "name": "n",
        "amount": {"kind": "count_selector", "multiply": -1, "selector": {
            "zone": "battlefield", "of": "you", "filter": {"subtype": "swamp"}}},
        "effects": [{"type": "pump", "params": {"power": "$n", "toughness": "$n", "selector": "all_creatures"}}],
    })])]


register("Mutilate", _mutilate)
