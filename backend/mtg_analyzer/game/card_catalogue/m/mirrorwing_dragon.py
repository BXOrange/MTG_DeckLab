from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Mirrorwing Dragon (spell-copy per other creature, retargeted)
# ===========================================================================
# New `mirrorwing_copy` effect — `RulesEngine.copy_spell` called once per
# other creature the caster controls, each with its own ``new_targets``.
# Flying folds in from the RULE 702 keyword catalogue.


def _mirrorwing_dragon() -> list[AbilitySpec]:
    """Flying
    Whenever a player casts an instant or sorcery spell that targets only
    this creature, that player copies that spell for each other creature
    they control that the spell could target. Each copy targets a different
    one of those creatures."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mirrorwing_copy", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group"},
                "spell_card_types": ["instant", "sorcery"],
            },
        ),
    ]


register("Mirrorwing Dragon", _mirrorwing_dragon)
