from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _emeria_s_call() -> list[AbilitySpec]:
    """Create two 4/4 white Angel Warrior creature tokens with flying. Non-Angel creatures you control gain
    indestructible until your next turn.

    — The sorcery *front* face of the MDFC (the back face is the land Emeria, Shattered Skyclave -- "As this land
    enters, you may pay 3 life. If you don't, it enters tapped. {T}: Add {W}." -- which the land-play path handles,
    same convention as Agadeem's Awakening). The tokens are `create_token`; the grant is a `grant_until` keyword
    static over the structured "creatures you control that are not Angels" group, locked when the spell resolves
    (``lock_group``, RULE 611.2c: only the creatures there then are affected) and lasting ``your_next_turn``
    (RULE 611.2b, Nissa, Vital Force's duration).
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("create_token", {
                "count": 2, "power": 4, "toughness": 4, "colors": ["W"], "subtypes": ["Angel", "Warrior"],
                "keywords": ["flying"], "token_name": "Angel Warrior",
            }),
            EffectSpec("grant_until", {
                "duration": "your_next_turn", "target_kind": None, "lock_group": True,
                "static": {"type": "grant_keyword", "params": {
                    "keywords": ["indestructible"],
                    "affects": {"zone": "battlefield", "of": "you",
                                "filter": {"card_type": "creature", "without_subtype": "Angel"}},
                }},
            }),
        ]),
    ]


register("Emeria's Call // Emeria, Shattered Skyclave", _emeria_s_call)
register("Emeria's Call", _emeria_s_call)
