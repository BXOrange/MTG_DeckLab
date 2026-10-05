from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spirit_water_revival() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may waterbend {6}.
    Draw two cards. If this spell's additional cost was paid, instead
    shuffle your graveyard into your library, draw seven cards, and you
    have no maximum hand size for the rest of the game.
    Exile Spirit Water Revival.

    — the additional-cost-paid *override* ("instead"): the plain "draw two"
    is gated `{"additional_cost_paid": False}`, the bigger line
    `{"additional_cost_paid": True}` (RULE 118.3's "instead" = the two
    branches are mutually exclusive complements, the `clash_won` idiom).
    "no maximum hand size for the rest of the game" is the new
    `no_max_hand_size_rest_of_game` effect (`GameState.no_max_hand_size_
    player_ids`). "Exile ~" is the self-exile-on-resolution tail.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": 2}, condition={"additional_cost_paid": False}),
                EffectSpec("shuffle_graveyard_into_library", {},
                           condition={"additional_cost_paid": True}),
                EffectSpec("draw", {"count": 7}, condition={"additional_cost_paid": True}),
                EffectSpec("no_max_hand_size_rest_of_game", {},
                           condition={"additional_cost_paid": True}),
                EffectSpec("exile", {"target_kind": None}),
            ],
            additional_cost={"waterbend": 6},
            additional_cost_optional=True,
        ),
    ]


register("Spirit Water Revival", _spirit_water_revival)
