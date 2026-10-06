from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _yunas_decision() -> list[AbilitySpec]:
    """Choose one —
    • Continue the Pilgrimage — Sacrifice a creature. If you do, draw a card, then you may put a creature card and/or a land card from your hand onto the battlefield.
    • Find Another Way — Return one or two target permanent cards from your graveyard to your hand.

    — PLAY-ALL (Counter Blitz). Mode 1 is `choose_objects` (sacrifice a creature) whose ``then`` ("if you do") draws and then runs a
    `put_from_hand_onto_battlefield` creature pick chained (``then_effects``, so the two choices don't overwrite each other) into a land pick. Mode 2 is `return_from_graveyard` over ``graveyard_permanent`` with one or two targets.
    """
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={"choose": 1, "options": [
                [EffectSpec("choose_objects", {
                    "action": "sacrifice", "what": "creature", "count": 1, "prompt": "Wähle eine Kreatur zum Opfern",
                    "then": [
                        {"type": "draw", "params": {"count": 1}},
                        {"type": "put_from_hand_onto_battlefield", "params": {
                            "criteria": {"type": "Creature"}, "count": 1, "then_effects": [
                                {"type": "put_from_hand_onto_battlefield", "params": {"criteria": {"type": "Land"}, "count": 1}},
                            ],
                        }},
                    ],
                })],
                [EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_permanent", "destination": "hand", "count": 1, "count_max": 2,
                })],
            ], "descriptions": [
                "Opfere eine Kreatur. Wenn du das tust, ziehe eine Karte, dann darfst du eine Kreaturen- und/oder Landkarte aus deiner Hand ausspielen.",
                "Nimm eine oder zwei Karten bleibender Karten aus deinem Friedhof auf die Hand.",
            ]},
        ),
    ]


register("Yuna's Decision", _yunas_decision)
