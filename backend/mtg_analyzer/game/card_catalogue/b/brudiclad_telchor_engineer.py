from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Brudiclad, Telchor Engineer (each other token becomes a copy) —
# PAR-60
# ===========================================================================
# New `brudiclad_combat` + `brudiclad_become_copies` effects (reuse
# `RulesEngine.become_copy`, RULE 707.2). The "creature tokens you control
# have haste" static folds in from the parser (re-added here).


def _brudiclad_telchor_engineer() -> list[AbilitySpec]:
    """Creature tokens you control have haste.
    At the beginning of combat on your turn, create a 2/1 blue Phyrexian Myr
    artifact creature token. Then you may choose a token you control. If you
    do, each other token you control becomes a copy of that token."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "keywords": ["haste"], "affects": "creatures_you_control", "tokens": True,
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("brudiclad_combat", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you"},
        ),
    ]


register("Brudiclad, Telchor Engineer", _brudiclad_telchor_engineer)
