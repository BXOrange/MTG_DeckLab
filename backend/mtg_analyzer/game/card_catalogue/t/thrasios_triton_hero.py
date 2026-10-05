from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thrasios_triton_hero() -> list[AbilitySpec]:
    """{4}: Scry 1, then reveal the top card of your library. If it's a
    land card, put it onto the battlefield tapped. Otherwise, draw a
    card.
    Partner (You can have two commanders if both have partner.)

    — MEC-12 (cEDH Kinnan). `scry` (already general) chained with an
    ENG-37 B5 `seq`: `reveal_top` stashes the top card as the `revealed`
    referent, then `if_else` on "is it a land" puts it onto the
    battlefield tapped (`put_revealed_card`) or draws. RULE 608.2's
    "suspend on a pending choice, resume once answered" already parks the
    reveal-and-branch clause until scry's own interactive choice is
    settled. Partner is a printed keyword, recognized independently.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("scry", {"count": 1}),
                EffectSpec("seq", {"effects": [
                    {"type": "reveal_top", "params": {"whose": "you"}},
                    {"type": "if_else", "params": {
                        "condition": {"kind": "is_card_type", "of": "revealed",
                                      "card_type": "land"},
                        "then": [{"type": "put_revealed_card",
                                  "params": {"destination": "battlefield_tapped"}}],
                        "else": [{"type": "draw", "params": {"count": 1}}],
                    }},
                ]}),
            ],
            cost={"mana": "{4}"},
        ),
    ]


register("Thrasios, Triton Hero", _thrasios_triton_hero)
