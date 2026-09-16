from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _smite_the_deathless() -> list[AbilitySpec]:
    """Smite the Deathless deals 3 damage to target creature. That
    creature loses indestructible until end of turn. If that creature
    would die this turn, exile it instead.

    — Imodane deck batch. One real target, reused via `grant_until`'s
    `previous_subject` pronoun idiom for both the keyword-removal and the
    die-to-exile grant.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 3, "target_kind": "creature"}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "remove_keyword", "params": {"keywords": ["indestructible"]}},
                }),
                EffectSpec("grant_die_to_exile_this_turn", {}),
            ],
        ),
    ]


register("Smite the Deathless", _smite_the_deathless)
