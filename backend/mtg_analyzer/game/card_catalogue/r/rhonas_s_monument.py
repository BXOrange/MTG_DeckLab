from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rhonas_s_monument() -> list[AbilitySpec]:
    """Green creature spells you cast cost {1} less to cast.
    Whenever you cast a creature spell, target creature you control gets +2/+2 and gains trample until
    end of turn.

    — Tramplesaurus Rex deck batch. The trigger is the parser's own claim; the discount is
    `cost_reduction` over creature spells narrowed by ``spell_color`` (the Medallion cycle's filter).
    """
    return [
        AbilitySpec("static", [EffectSpec("cost_reduction", {
            "affects": "your_spells", "generic": 1, "spell_type": "creature", "spell_color": "G",
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"power": 2, "toughness": 2, "keywords": ["trample"],
                                 "target_kind": "creature_you_control"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                     "spell_filter": {"card_type": "creature"}},
        ),
    ]


register("Rhonas's Monument", _rhonas_s_monument)
