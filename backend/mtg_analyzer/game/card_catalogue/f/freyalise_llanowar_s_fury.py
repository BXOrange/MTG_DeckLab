from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _freyalise_llanowars_fury() -> list[AbilitySpec]:
    """+2: Create a 1/1 green Elf Druid creature token with "{T}: Add {G}."
    −2: Destroy target artifact or enchantment.
    −6: Draw a card for each green creature you control.
    Freyalise, Llanowar's Fury can be your commander.

    — PLAY-ALL Step 2 (Raggadragga). The two minus abilities are the
    parser's own claims, reproduced verbatim. The +2 is a `create_token`
    whose ``oracle_text`` carries the quoted mana ability — a token's mana
    abilities are read off its own text (`mana_abilities_for`), the same way
    a printed creature's are. The commander clause is deck-building text
    with no game behaviour of its own.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Elf", "Druid"], "keywords": [], "token_name": "Elf Druid",
                "oracle_text": "{T}: Add {G}.",
            })],
            cost={"loyalty": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("destroy", {"target_kind": "artifact_or_enchantment"})],
            cost={"loyalty": -2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {
                    "kind": "count_selector",
                    "selector": {"zone": "battlefield", "of": "you", "filter": {"color": "G", "card_type": "creature"}},
                },
                "effects": [{"type": "draw", "params": {"count": "$n"}}],
            })],
            cost={"loyalty": -6},
        ),
    ]


register("Freyalise, Llanowar's Fury", _freyalise_llanowars_fury)
