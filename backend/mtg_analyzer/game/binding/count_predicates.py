"""Trigger intervening-if predicates over turn and combat counts (Commander Cube singleton batch).

Two trigger keys the binder reads, each a RULE 603.4 intervening-if on the triggering event:

* ``spells_cast_this_turn_at_least`` (Geralf, the Fleshwright): "other than your first spell that turn" is the
  casting player's spell count being at least 2. `GameState.spells_cast_this_turn` is already incremented before a
  SPELL_CAST trigger is checked (see `_nth_spell_ok` in `core.py`), so the event's own spell is counted.
* ``other_attackers_at_least`` (Glimmer Lens): "at least one other creature attacks" counts every attacking creature
  except the triggering one (RULE 508.1). A creature is attacking from declaration until it leaves combat (RULE 506.4).

`core.py` calls `count_trigger_predicates` once with the trigger dict and appends whatever it returns.
"""
from __future__ import annotations

from typing import Any, Callable


def count_trigger_predicates(trigger: dict[str, Any]) -> list[Callable[[Any, Any], bool]]:
    predicates: list[Callable[[Any, Any], bool]] = []

    minimum_spells = trigger.get("spells_cast_this_turn_at_least")
    if minimum_spells is not None:
        def _spells_at_least(event: Any, context: Any, n: int = int(minimum_spells)) -> bool:
            return context.state.spells_cast_this_turn.get(event.get("player_id"), 0) >= n

        predicates.append(_spells_at_least)

    minimum_others = trigger.get("other_attackers_at_least")
    if minimum_others is not None:
        def _other_attackers_at_least(event: Any, context: Any, n: int = int(minimum_others)) -> bool:
            # RULE 508.1: every attacking creature is counted; the triggering creature is one of them and is excluded.
            attackers = sum(1 for o in context.state.battlefield if o.is_creature and o.attacking)
            return attackers - 1 >= n

        predicates.append(_other_attackers_at_least)

    return predicates
