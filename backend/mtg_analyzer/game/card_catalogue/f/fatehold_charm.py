from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    # RULE 700.2 / 601.2b: choose one mode when announcing the spell.
    return [AbilitySpec("spell_effect", [], modes={"choose": 1, "options": [
        [EffectSpec("draw", {"count": 1}), EffectSpec("empower_jace", {"count": 2})],
        [EffectSpec("return_to_hand", {"target_kind": "spell_or_creature", "spell_or_permanent": True})],
        [EffectSpec("pump", {"selector": "creatures_you_control", "power": 1, "toughness": 2})],
    ], "descriptions": ["Draw a card. Empower Jace 2.",
                        "Return target spell or creature to its owner's hand.",
                        "Creatures you control get +1/+2 until end of turn."]})]


register("Fatehold Charm", _card)
