from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _omnath_locus_of_the_void() -> list[AbilitySpec]:
    """Omnath gets +1/+1 for each unspent mana you have.
    If you would lose unspent mana, that mana becomes colorless instead.
    Landfall — Whenever a land you control enters, add {C}{C}.

    — PLAY-ALL (Multiverse Reforged). The P/T clause is `anthem`'s ``power_count``/``toughness_count`` over the new
    ``unspent_mana_you_have`` count selector (`continuous.count_selector`, the controller's whole pool). The replacement is the
    ``unspent_mana_colorless`` static, read by `continuous.empty_mana_pool`: unrestricted mana that would empty stays as
    colourless. **Simplification:** restricted mana lots still empty as ever. Landfall is the parser's own claim.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 1,
                "power_count": "unspent_mana_you_have", "toughness_count": "unspent_mana_you_have",
            })],
        ),
        AbilitySpec("static", [EffectSpec("unspent_mana_colorless", {})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["C", "C"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False, "type": "land"}},
        ),
    ]


register("Omnath, Locus of the Void", _omnath_locus_of_the_void)
