from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _here_comes_a_new_hero() -> list[AbilitySpec]:
    """Draw X for a target player and copy up to one creature of mana value X or less."""
    return [AbilitySpec("spell_effect", [
        EffectSpec("draw", {"target_kind": "player", "count": "x"}),
        EffectSpec("copy_permanent", {"target_kind": "creature", "target_optional": True, "max_mana_value": "x"}),
    ])]


register('Here Comes a New Hero!', _here_comes_a_new_hero)
