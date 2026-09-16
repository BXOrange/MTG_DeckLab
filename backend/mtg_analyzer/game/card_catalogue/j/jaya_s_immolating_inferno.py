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
    spell in this catalogue already reads it. **Documented
    simplification**: the Legendary Sorcery casting restriction (control
    a legendary creature or planeswalker) isn't enforced — no card-type-
    supertype casting gate exists in `can_cast` yet — so the spell casts
    like an ordinary sorcery; the damage itself is fully modeled.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": "x", "target_kind": "any", "count": 3, "optional": True})],
        ),
    ]


register("Jaya's Immolating Inferno", _jayas_immolating_inferno)
