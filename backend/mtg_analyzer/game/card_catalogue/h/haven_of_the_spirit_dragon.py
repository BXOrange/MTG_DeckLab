from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _haven_of_the_spirit_dragon() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}: Add one mana of any color. Spend this mana only to cast a Dragon creature spell.
    {2}, {T}, Sacrifice this land: Return target Dragon creature card or Ugin planeswalker card from your
    graveyard to your hand.

    — Reign of Dragons deck batch. Both mana abilities are read off the printed text. The third is a
    graveyard `return_from_graveyard` to hand over your graveyard's permanent cards narrowed by an
    ``any_of`` filter (a Dragon creature, or an Ugin planeswalker) — "Dragon creature card or Ugin
    planeswalker card" is two different type/subtype pairs, which one flat filter cannot express.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_permanent", "destination": "hand",
                "creature_filter": {"any_of": [
                    {"card_type": "creature", "subtype": "dragon"},
                    {"card_type": "planeswalker", "subtype": "ugin"},
                ]},
            })],
            cost={"text": "{2}, {t}, sacrifice ~"},
            raw_text="{2}, {t}, sacrifice ~: return target dragon creature card or ugin planeswalker card from your graveyard to your hand.",
        ),
    ]


register("Haven of the Spirit Dragon", _haven_of_the_spirit_dragon)
