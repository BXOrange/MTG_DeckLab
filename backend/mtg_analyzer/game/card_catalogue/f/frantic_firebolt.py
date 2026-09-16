from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _frantic_firebolt() -> list[AbilitySpec]:
    """Frantic Firebolt deals X damage to target creature, where X is 2
    plus the number of cards in your graveyard that are instant cards,
    sorcery cards, and/or have an Adventure.

    — Imodane deck batch. `DealDamageEffect`'s new `amount_from_count_
    selector`/`amount_plus_count_selector`, reading the new
    `instant_sorcery_or_adventure_cards_in_your_graveyard` count.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "target_kind": "creature",
                "amount_from_count_selector": "instant_sorcery_or_adventure_cards_in_your_graveyard",
                "amount_plus_count_selector": 2,
            })],
        ),
    ]


register("Frantic Firebolt", _frantic_firebolt)
