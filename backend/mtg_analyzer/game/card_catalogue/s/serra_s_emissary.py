from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _serras_emissary() -> list[AbilitySpec]:
    """Flying
    As this creature enters, choose a card type.
    You and creatures you control have protection from the chosen card type.

    — PLAY-ALL (Multiverse Reforged). Flying is the keyword's. The choice is the new `choose_card_type_on_enter` RULE 601.2b
    replacement (`ChooseCardTypeReplacement`, stored on `GameObject.chosen_type` as the plural protection-quality word). The
    protection is `grant_protection_static`'s ``protection_from_chosen_type`` over ``creatures_you_control`` plus the new
    ``protects_controller`` half (`continuous.player_static_protections`, consulted by `RulesEngine.deal_damage` — damage is
    the only DEBT letter a player is subject to here). **Simplification:** Kindred is not offered as a card type.
    """
    return [
        AbilitySpec("enter_replacement", [EffectSpec("choose_card_type_on_enter", {})]),
        AbilitySpec(
            "static",
            [EffectSpec("grant_protection_static", {
                "affects": "creatures_you_control", "protection_from_chosen_type": True, "protects_controller": True,
            })],
        ),
    ]


register("Serra's Emissary", _serras_emissary)
