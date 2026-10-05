from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sign_in_blood() -> list[AbilitySpec]:
    """Target player draws two cards and loses 2 life.

    — ENG-37 B4: a `seq` whose first clause (`draw`) carries the sole RULE 115
    player target and whose second (`lose_life` with ``previous_subject``)
    acts on that same player via `GameContext.previous_targets`, retiring the
    fused ``target_player_draw_lose_life``. One announced target, as before —
    `lose_life` declares none of its own.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "draw", "params": {"count": 2, "target_kind": "player"}},
                {"type": "lose_life", "params": {"amount": 2, "previous_subject": True}},
            ]})],
        )
    ]


register("Sign in Blood", _sign_in_blood)
