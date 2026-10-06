from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _continue() -> list[AbilitySpec]:
    """Return up to four targeted creature cards that died this turn (RULE 400.7)."""
    return [AbilitySpec("spell_effect", [EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "count": 4, "optional": True,
        "creature_filter": {"died_this_turn": True},
    })])]


register('Continue?', _continue)
