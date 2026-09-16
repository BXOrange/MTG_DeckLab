from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _voltage_surge() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may sacrifice an
    artifact.
    Voltage Surge deals 2 damage to target creature or planeswalker. If
    this spell's additional cost was paid, Voltage Surge deals 4 damage
    instead.

    — Imodane deck batch. **Documented simplification**: the optional
    "you may sacrifice an artifact" additional cost isn't modeled —
    `AbilitySpec.additional_cost`'s closed vocabulary has no *optional*
    sacrifice shape (RULE 702.157's own Bargain keyword is the one
    optional-sacrifice-as-you-cast mechanic this engine has, and this
    card doesn't print it), so building a parallel one-off "may" cost path
    is disproportionate to this one card. Modeled as the unconditional
    base "deals 2 damage" — never the upgraded 4, and never actually
    asking for an artifact.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 2, "target_kind": "creature_or_planeswalker"})],
        ),
    ]


register("Voltage Surge", _voltage_surge)
