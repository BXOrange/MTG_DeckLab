from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "If an Insect card was milled this way" — also true of Grist herself (an Insect creature card outside the battlefield).
_INSECT_MILLED = {"kind": "milled_subtype_this_way", "subtype": "insect", "name": "source"}


def _grist_the_hunger_tide() -> list[AbilitySpec]:
    """As long as Grist isn't on the battlefield, it's a 1/1 Insect creature in addition to its other types.
    +1: Create a 1/1 black and green Insect creature token, then mill a card. If an Insect card was milled this way, put a loyalty counter on Grist and repeat this process.
    −2: You may sacrifice a creature. When you do, destroy target creature or planeswalker.
    −5: Each opponent loses life equal to the number of creature cards in your graveyard.

    — PLAY-ALL (Death Toll). The +1 is Hoarder's Greed's `repeat_process`, whose ``repeat_while`` now also takes an `effect_conditions` dict
    (`milled_subtype_this_way`, read after each pass). **Documented simplification**: the "isn't on the battlefield, it's a 1/1 Insect
    creature" static is not a characteristic-changing effect off the battlefield; its two observable consequences are authored directly —
    Grist milled by her own +1 counts as an Insect card (``name: "source"``), and Grist in your graveyard adds one to the −5's count
    (``cards_named_source_in_all_graveyards``). The −2 is `sacrifice_chosen_then` with a RULE 603.12 reflexive trigger.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("repeat_process", {
                "effects": [
                    {"type": "create_token", "params": {
                        "count": 1, "power": 1, "toughness": 1, "colors": ["B", "G"], "subtypes": ["Insect"], "token_name": "Insect",
                    }},
                    {"type": "mill", "params": {"count": 1}},
                    {"type": "if_else", "params": {
                        "condition": _INSECT_MILLED,
                        "then": [{"type": "add_counters", "params": {"count": 1, "kind": "loyalty"}}],
                    }},
                ],
                "repeat_while": _INSECT_MILLED,
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("sacrifice_chosen_then", {
                "what": "creature", "count": 1, "optional": True,
                "trigger": [{"type": "destroy", "params": {"target_kind": "creature_or_planeswalker"}}],
            })],
            cost={"loyalty": -2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("lose_life", {
                "selector": "each_opponent",
                "amount": {"kind": "count_selector", "selector": {"terms": [
                    {"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"}},
                    "cards_named_source_in_all_graveyards",
                ]}},
            })],
            cost={"loyalty": -5},
        ),
    ]


register("Grist, the Hunger Tide", _grist_the_hunger_tide)
