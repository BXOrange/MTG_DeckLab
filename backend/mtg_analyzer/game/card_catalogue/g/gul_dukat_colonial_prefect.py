from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gul_dukat_colonial_prefect() -> list[AbilitySpec]:
    """Menace
    At the beginning of each end step, each opponent loses life equal to the life that player lost this turn. You gain life equal to the life lost this way. (Damage causes loss of life.)

    RULE 119.3 / 608.2c: each opponent loses what they already lost this
    turn, so the total lost this way equals the opponents' combined
    life-lost-this-turn tally *before* the losses. The gain is therefore
    resolved first from that tally (net result identical, nothing
    interleaves a single resolution). Menace folds in from the keyword catalogue.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("gain_life", {"count_selector": "opponents_life_lost_this_turn"}),
                EffectSpec("for_each", {
                    "over": {"players": "each_opponent"},
                    "effects": [{"type": "lose_life", "params": {
                        "player": {"of": "target"},
                        "amount": {"kind": "count_selector", "selector": "life_lost_this_turn", "of": "target"},
                    }}],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
        ),
    ]


register("Gul Dukat, Colonial Prefect", _gul_dukat_colonial_prefect)
