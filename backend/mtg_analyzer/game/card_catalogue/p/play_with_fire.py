from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _play_with_fire() -> list[AbilitySpec]:
    """Play with Fire deals 2 damage to any target. If a player is dealt
    damage this way, scry 1.

    — Imodane deck batch. The scry rider is `ConditionalEffect`'s new
    ``target_is_player`` condition key (this batch, shares its shared-
    targets-list idiom with the existing ``target_is_controller``), same
    shape as Trystan's ``graveyard_has_type``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 2, "target_kind": "any"}),
                EffectSpec("scry", {"amount": 1}, condition={"target_is_player": True}),
            ],
        ),
    ]


register("Play with Fire", _play_with_fire)
