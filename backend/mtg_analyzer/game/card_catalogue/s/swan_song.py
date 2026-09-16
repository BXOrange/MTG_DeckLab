from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _swan_song() -> list[AbilitySpec]:
    """Counter target enchantment, instant, or sorcery spell. Its controller
    creates a 2/2 blue Bird creature token with flying.

    — Swan Song. ENG-37 B3: a `seq` of `counter` (``card_types`` restricts the
    legal spell targets) then `create_token` with ``creators="previous_target_
    controller"`` — the countered spell object keeps its ``controller_id`` in
    the graveyard (RULE 608.2h) — retiring the fused ``counter_create_token``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "counter", "params": {
                    "card_types": ["enchantment", "instant", "sorcery"],
                }},
                {"type": "create_token", "params": {
                    "power": 2, "toughness": 2, "colors": ["U"],
                    "subtypes": ["Bird"], "keywords": ["flying"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Swan Song", _swan_song)
