from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hope_of_ghirapur() -> list[AbilitySpec]:
    """Flying
    Sacrifice Hope of Ghirapur: Until your next turn, target player who was
    dealt combat damage by Hope of Ghirapur this turn can't cast noncreature
    spells.

    — Hope of Ghirapur. Two firsts here, both forced by the card:

    * a **history-filtered target kind** (`targeting.py`'s
      ``player_dealt_combat_damage_by_source``). By the time the sacrifice
      ability is activated the combat damage step is long over and nothing
      on the board records who got hit, so `GameState.
      combat_damage_to_players_this_turn` keeps the tally (keyed by source,
      so two copies each track their own victims). With no one hit this
      turn the ability simply has no legal target and RULE 601.2c makes it
      unactivatable — exactly right, and fail-closed.
    * a **player-scoped cast prohibition with no permanent behind it**
      (`PlayerCastRestrictionEffect`). Hope has sacrificed *itself* to pay
      for this, so there is nothing for `continuous.recompute` to read a
      static off; it lives on `Player.player_effects` for the same reason
      the RULE 615 damage shield does, and lapses when the *controller's*
      next turn begins (RULE 611.2b, swept in `GameEngine.begin_turn`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("player_cast_restriction", {"noncreature": True})],
            cost={"sacrifice": "self"},
        ),
    ]


register("Hope of Ghirapur", _hope_of_ghirapur)
