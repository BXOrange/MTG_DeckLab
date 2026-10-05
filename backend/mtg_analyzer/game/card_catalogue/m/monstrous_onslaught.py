from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _monstrous_onslaught() -> list[AbilitySpec]:
    """Monstrous Onslaught deals X damage divided as you choose among any number of target creatures,
    where X is the greatest power among creatures you control as you cast this spell.

    — Tramplesaurus Rex deck batch. Fire Covenant's `damage` (``divided``, ten-target announce cap,
    even-split simplification) with X from the ``greatest_power_among_creatures_you_control`` count
    selector. **Documented simplification:** X is read as the spell resolves rather than "as you cast
    it" — the two differ only if a creature's power changes in response.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("damage", {
            "amount_from_count_selector": "greatest_power_among_creatures_you_control",
            "target_kind": "creature", "count": 10, "optional": True, "divided": True,
        })]),
    ]


register("Monstrous Onslaught", _monstrous_onslaught)
