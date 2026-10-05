from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fateful_absence() -> list[AbilitySpec]:
    """Destroy target creature or planeswalker. Its controller investigates.

    — PLAY-ALL (Calling All Angels). `destroy`, then a Clue `create_token` whose ``creators`` is the destroyed permanent's
    controller (`previous_target_controller`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"target_kind": "creature_or_planeswalker"}),
                EffectSpec("create_token", {"count": 1, "token_name": "Clue", "creators": "previous_target_controller"}),
            ],
        ),
    ]


register("Fateful Absence", _fateful_absence)
