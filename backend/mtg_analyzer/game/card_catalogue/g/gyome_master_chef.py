from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Gyome / Jadar (new per-turn tracker + keyword-scoped condition)
# ===========================================================================
# Engine: `GameState.nontoken_creatures_entered_this_turn` +
# `continuous.count_selector` ``nontoken_creatures_you_entered_this_turn``;
# `static_conditions` kind ``control_no_creatures_with_keyword``.


def _gyome_master_chef() -> list[AbilitySpec]:
    """Trample
    At the beginning of your end step, create a number of Food tokens equal
    to the number of nontoken creatures you had enter the battlefield under
    your control this turn.
    {1}, Sacrifice a Food: Target creature gains indestructible until end of
    turn. Tap it."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Food",
                "count_selector": "nontoken_creatures_you_entered_this_turn",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("pump", {"keywords": ["indestructible"], "target_kind": "creature"}),
                EffectSpec("tap", {"target_kind": None}),
            ],
            cost={"text": "{1}, Sacrifice a Food"},
        ),
    ]


register("Gyome, Master Chef", _gyome_master_chef)
