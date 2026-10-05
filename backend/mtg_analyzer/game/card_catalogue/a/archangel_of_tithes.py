from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The printed tax per creature, in generic mana.
_TAX = 1


def _archangel_of_tithes() -> list[AbilitySpec]:
    """Flying
    As long as this creature is untapped, creatures can't attack you or planeswalkers you control unless their controller pays {1} for each of those creatures.
    As long as this creature is attacking, creatures can't block unless their controller pays {1} for each of those creatures.

    — PLAY-ALL (Calling All Angels). The attack half is the parser's `attack_tax` marker (RULE 508.1g), now honouring its
    ``active_if`` gate (it used to be ignored, taxing even while tapped). The block half is the new `block_tax` marker
    (RULE 509.1c, `continuous.block_tax_per_creature`, paid in `declare_blockers`): any controller's blockers, gated on
    the source attacking.
    """
    return [
        AbilitySpec("static", [EffectSpec("attack_tax", {
            "defender_scope": "player_or_planeswalker", "amount": _TAX, "active_if": {"kind": "source_untapped"},
        })]),
        AbilitySpec("static", [EffectSpec("block_tax", {
            "amount": _TAX, "active_if": {"kind": "source_attacking"},
        })]),
    ]


register("Archangel of Tithes", _archangel_of_tithes)
