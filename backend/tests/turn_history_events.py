"""Fire the events the per-turn history is derived from (ENG-47).

`GameState`'s "… this turn" tallies (spells cast, life gained, creatures died, damage dealt, …)
are derived from the turn-stamped event log, so a test that wants "the opponent has cast three
spells this turn" fires three `SPELL_CAST` events instead of assigning a counter. The payload
here is exactly what the engine's own fire sites stamp.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from mtg_analyzer.models.cards.card import Card  # noqa: F401  (re-exported for tests)
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone  # noqa: F401


def _fire(state: Any, event_type: str, **data: Any) -> None:
    state.fire_event(GameEvent(event_type, **data))


def cast_spell(
    state: Any, player_id: str, *, types: Iterable[str] = ("instant",), colors: Iterable[str] = (),
    mana_value: int = 0, has_x: bool = False, subtypes: Iterable[str] = (), times: int = 1,
) -> None:
    for _ in range(times):
        _fire(state, EventType.SPELL_CAST, player_id=player_id, object_types=sorted(types),
              colors=sorted(colors), mana_value=mana_value, has_x=has_x, subtypes=list(subtypes),
              from_hand=True, from_zone="hand")


def gain_life(state: Any, player_id: str, amount: int) -> None:
    _fire(state, EventType.LIFE_GAINED, player_id=player_id, amount=amount)


def lose_life(state: Any, player_id: str, amount: int) -> None:
    _fire(state, EventType.LIFE_LOST, player_id=player_id, amount=amount, cause="effect")


def draw(state: Any, player_id: str, count: int = 1, ids: Optional[list[int]] = None) -> None:
    _fire(state, EventType.DRAW, player_id=player_id, count=count, instance_ids=list(ids or []))


def discard(state: Any, player_id: str, count: int = 1) -> None:
    for _ in range(count):
        _fire(state, EventType.DISCARD_CARD, player_id=player_id, object_types=["creature"])


def creature_died(state: Any, controller_id: str, *, counters: Optional[dict[str, int]] = None) -> None:
    _fire(state, EventType.DIES, controller_id=controller_id, owner_id=controller_id,
          object_types=["creature"], counters=dict(counters or {}))


def damage(
    state: Any, *, source_id: int, source_controller_id: Optional[str], target_id: Any, amount: int = 1,
    combat: bool = False, is_player: bool = True, target_is_creature: bool = False,
) -> None:
    _fire(state, EventType.DAMAGE, amount=amount, is_player=is_player, target_id=target_id,
          source_id=source_id, source_controller_id=source_controller_id, combat=combat,
          target_is_creature=target_is_creature)


def entered(state: Any, obj: Any) -> None:
    """The ENTERS_BATTLEFIELD an engine entry path fires after `add_to_battlefield`."""
    _fire(state, EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id, object=obj.name,
          instance_id=obj.instance_id, object_types=sorted(obj.type_words))


def left(state: Any, obj: Any) -> None:
    """The LEAVES_BATTLEFIELD an engine departure path fires after `remove_from_battlefield`."""
    _fire(state, EventType.LEAVES_BATTLEFIELD, controller_id=obj.controller_id, owner_id=obj.owner_id,
          object=obj.name, instance_id=obj.instance_id, object_types=sorted(obj.type_words),
          counters=dict(obj.counters))


def declared_attack(state: Any, player_id: str) -> None:
    """The ATTACKS event `declare_attackers` fires for a declared attacker."""
    _fire(state, EventType.ATTACKS, player_id=player_id, attacker="A", instance_id=0,
          object_types=["creature", "permanent"], declared=True)


def begin_combat(state: Any, times: int = 1) -> None:
    """``times`` combat phases have begun this turn."""
    for _ in range(times):
        _fire(state, EventType.STEP_BEGIN, step="begin_combat", phase="combat")
