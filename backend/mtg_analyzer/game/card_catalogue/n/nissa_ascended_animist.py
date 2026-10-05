from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nissa_ascended_animist() -> list[AbilitySpec]:
    """Compleated ({G/P} can be paid with {G} or 2 life. For each {G/P} paid
    with life, this planeswalker enters with two fewer loyalty counters.)
    +1: Create an X/X green Phyrexian Horror creature token, where X is
    Nissa's loyalty.
    −1: Destroy target artifact or enchantment.
    −7: Until end of turn, creatures you control get +1/+1 for each Forest
    you control and gain trample.

    — PLAY-ALL Step 2 (Kodama). The −1 is the parser's own claim; Compleated
    is a printed keyword read from the card. The +1 is `create_token` with
    ``pt_amount`` — a `counters` amount operand over this planeswalker's own
    loyalty, measured as the ability resolves (the loyalty cost is already
    paid, so the +1 counts). The −7 is a `bind` that measures the Forests
    once (a `count_selector` over a {zone, of, filter: subtype forest}
    selector, Freyalise's shape) and pumps every creature you control by
    that much with trample, until end of turn.
    """
    forests = {"zone": "battlefield", "of": "you", "filter": {"subtype": "forest"}}
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "colors": ["G"], "subtypes": ["Phyrexian", "Horror"], "keywords": [],
                "token_name": "Phyrexian Horror",
                "pt_amount": {"kind": "counters", "counter": "loyalty", "of": "source"},
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("destroy", {"target_kind": "artifact_or_enchantment"})],
            cost={"loyalty": -1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "count_selector", "selector": dict(forests)},
                "effects": [{"type": "pump", "params": {
                    "power": "$n", "toughness": "$n", "keywords": ["trample"],
                    "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
                }}],
            })],
            cost={"loyalty": -7},
        ),
    ]


register("Nissa, Ascended Animist", _nissa_ascended_animist)
