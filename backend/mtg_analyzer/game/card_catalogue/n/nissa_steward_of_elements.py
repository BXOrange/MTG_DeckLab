from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nissa_steward_of_elements() -> list[AbilitySpec]:
    """+2: Scry 2.
    0: Look at the top card of your library. If it's a land card or a
    creature card with mana value less than or equal to the number of
    loyalty counters on Nissa, Steward of Elements, you may put that card
    onto the battlefield.
    −6: Untap up to two target lands you control. They become 5/5
    Elemental creatures with flying and haste until end of turn. They're
    still lands.

    — MEC-41. +2 is the already-shipped plain ``scry`` effect. The 0
    ability is an ENG-37 B5 `seq`: `reveal_top` stashes the top card as
    the `revealed` referent, an `if_else` gates on "land **or** (creature
    **and** its mana value ≤ this planeswalker's loyalty)" (`any`/`all`
    combinators + an `amount_compare` of `characteristic(mana_value, of:
    revealed)` against `counters(loyalty, of: source)`), and its `then` is
    an `optional` (RULE 601.2b "you may") wrapping `put_revealed_card`
    onto the battlefield. The −6 reuses Kamahl,
    Heart of Krosa's own "target land becomes a creature until end of
    turn, still a land" `grant_until`/`type_change`+`grant_keyword` chain
    (MEC-12) verbatim, just widened to "up to two" targets — `TapEffect`'s
    own pre-existing "untap up to two target lands" shape (Snap-shaped) —
    instead of Kamahl's single one.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("scry", {"count": 2})],
            cost={"loyalty": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("seq", {"effects": [
                {"type": "reveal_top", "params": {"whose": "you"}},
                {"type": "if_else", "params": {
                    "condition": {"kind": "any", "conditions": [
                        {"kind": "is_card_type", "of": "revealed", "card_type": "land"},
                        {"kind": "all", "conditions": [
                            {"kind": "is_card_type", "of": "revealed", "card_type": "creature"},
                            {"kind": "amount_compare", "op": "le",
                             "left": {"kind": "characteristic",
                                      "characteristic": "mana_value", "of": "revealed"},
                             "right": {"kind": "counters",
                                       "counter": "loyalty", "of": "source"}},
                        ]},
                    ]},
                    "then": [{"type": "optional", "params": {
                        "effects": [{"type": "put_revealed_card",
                                     "params": {"destination": "battlefield"}}],
                        "prompt": "Karte ins Spiel bringen?",
                    }}],
                    "else": [],
                }},
            ]})],
            cost={"loyalty": 0},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("tap", {
                    "target_kind": "land_you_control", "count": 2, "optional": True, "untap": True,
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "add_subtypes": ["Elemental"],
                        "power": 5, "toughness": 5,
                    }},
                    "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "grant_keyword", "params": {"keywords": ["flying", "haste"]}},
                    "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
                }),
            ],
            cost={"loyalty": -6},
        ),
    ]


register("Nissa, Steward of Elements", _nissa_steward_of_elements)
