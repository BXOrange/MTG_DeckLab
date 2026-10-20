from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mox_diamond() -> list[AbilitySpec]:
    """If this artifact would enter, you may discard a land card instead.
    If you do, put this artifact onto the battlefield. If you don't, put
    it into its owner's graveyard.
    {T}: Add one mana of any color.

    — RULE 614.12's own worked example. A before-entry instruction
    (`entry_effect`, the Dermotaxi family): "you may discard a land card" is a
    `pay_cost_then` whose "if you don't" branch is `put_entering_into_graveyard`
    (declining, or having no land to discard, means this never becomes a
    permanent at all); paying simply lets the entry continue. The mana ability
    itself needs no hand-authoring: a plain "{T}: Add one mana of any color."
    is recognized generically by `mana_abilities_for`.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("entry_effect", {"effects": [
                {"type": "pay_cost_then", "params": {
                    "cost": "Discard a land card",
                    "effects": [],
                    "else_effects": [{"type": "put_entering_into_graveyard", "params": {}}],
                    "prompt": "Land abwerfen, um es ins Spiel zu bringen?",
                }},
            ]})],
        ),
    ]


register("Mox Diamond", _mox_diamond)
