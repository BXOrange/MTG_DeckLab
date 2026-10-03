from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jayas_immolating_inferno() -> list[AbilitySpec]:
    """(You may cast a legendary sorcery only if you control a legendary
    creature or planeswalker.)
    Jaya's Immolating Inferno deals X damage to each of up to three
    targets.

    — Imodane deck batch. "To each of up to three targets" is
    `DealDamageEffect`'s existing ``count``/``optional`` "up to N
    targets" shape (Volcanic Salvo-shaped), unchanged; X is the spell's
    own announced {X}, substituted the same way every other X-damage
    spell in this catalogue already reads it. The RULE 205.4d cast gate
    requires a legendary creature or planeswalker under your control.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": "x", "target_kind": "any", "count": 3, "optional": True})],
            cast_condition={"control_legendary_creature_or_planeswalker": True},
        ),
    ]


register("Jaya's Immolating Inferno", _jayas_immolating_inferno)
