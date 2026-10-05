from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mutiny() -> list[AbilitySpec]:
    """Target creature an opponent controls deals damage equal to its power
    to another target creature that player controls.

    — Mutiny. The one-sided "fight" shape `effects.DamageEqualToPowerEffect`
    already implements for Rabid Bite ("target creature you control deals
    damage equal to its power to target creature you don't control") — only
    the *dealer* here is also an opponent's creature (RULE 115.1a two
    independent `creature_you_dont_control` targets, `extra_target_specs`),
    not the caster's own.

    Documented simplification: RAW's "**that player**" ties the second
    target to the specific opponent who controls the first (only matters at
    3+ players); both targets are modeled as plain "an opponent controls"
    independently rather than tracking which specific opponent the first
    pick named — the two coincide by construction in any 2-player game, and
    no card in scope needs the distinction (no "same specific opponent"
    targeting constraint exists in this engine yet).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage_equal_to_power", {
                "dealer_kind": "creature_you_dont_control",
                "target_kind": "creature_you_dont_control",
            })],
        ),
    ]


register("Mutiny", _mutiny)
