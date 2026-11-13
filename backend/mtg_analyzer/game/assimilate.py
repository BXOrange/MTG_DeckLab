"""RULE 701.72 Assimilate: gain control or enter under control, +1/+1 counter, Borg artifact creature.

Three pieces, each tied to a rule clause:

* `assimilate` performs the keyword action (701.72a for a permanent, 701.72b for a permanent card in another zone).
* The "is a Borg artifact creature" half is a layer-4 floating static (RULE 613.1d) pinned to the exact battlefield
  visit, so it lasts as long as the permanent stays and a later visit of the same card is a new object (RULE 400.7).
* `GameState.assimilated_visits` is the RULE 701.72c / 607.2a link between the ability that assimilates and the
  abilities that read "assimilated with [this object]": the source's own battlefield visit maps to the exact visits it
  assimilated, so a permanent that left and came back is no longer in the pool.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Optional

from ..models.cards import card_query
from ..models.game.game_object import Zone

if TYPE_CHECKING:
    from ..models.game.game_object import GameObject
    from ..models.game.game_state import GameState

#: RULE 701.72a: the creature type the assimilated permanent has instead of its own ("Borg artifact creature").
BORG_CREATURE_TYPE = "Borg"
#: RULE 701.72a: the card types it gains; every other type, supertype and non-creature subtype stays (613.1d adds).
ASSIMILATED_ADDED_TYPES = ("artifact", "creature")
#: RULE 701.72a/b: the counter it gets, and how many.
ASSIMILATE_COUNTER_KIND = "+1/+1"
ASSIMILATE_COUNTER_COUNT = 1


def assimilated_with(state: "GameState", source: Optional["GameObject"],
                     incarnation: Optional[int] = None) -> list["GameObject"]:
    """RULE 701.72c / 607.2a: the battlefield permanents this exact visit of ``source`` assimilated.

    A permanent that left the battlefield and returned is a new object (RULE 400.7), so its recorded visit no
    longer matches and it is not in the pool; control changes since do not matter.
    """
    if source is None:
        return []
    if incarnation is None:
        incarnation = source.zone_incarnation
    pool = []
    for instance_id, visit in state.assimilated_visits.get((source.instance_id, incarnation), []):
        obj = state.find_object(instance_id)
        if obj is not None and obj.zone == Zone.BATTLEFIELD and obj.zone_incarnation == visit:
            pool.append(obj)
    return pool


def _borg_type_change(state: "GameState", obj: "GameObject", visit: int, source: Optional["GameObject"],
                      controller_id: str):
    """The layer-4 effect that makes one battlefield visit of ``obj`` a Borg artifact creature (RULE 613.1d)."""
    from .effects.core import StaticAbility

    ability = StaticAbility(
        "type", affects="objects", source=source if source is not None else obj,
        params={
            "add_types": list(ASSIMILATED_ADDED_TYPES),
            # RULE 205.3m / 701.72a: only the creature types are replaced, so Equipment, Vehicle and the like stay.
            "set_creature_types": [BORG_CREATURE_TYPE],
            "object_incarnations": {obj.instance_id: visit},
        },
        duration="rest_of_game", description="Assimilate: Borg artifact creature",
    )
    ability.object_ids = [obj.instance_id]
    # RULE 611.2a: a floating effect's "you" is the player who created it, even if its source later changes hands.
    ability.duration_data = {"player_id": controller_id, "turn": state.internal_turn.number}
    ability.timestamp = state.next_timestamp()
    state.floating_statics.append(ability)
    return ability


def assimilate(engine, controller_id: str, obj: "GameObject", source: Optional["GameObject"] = None,
               source_incarnation: Optional[int] = None) -> Optional["GameObject"]:
    """Perform RULE 701.72 on ``obj`` for ``controller_id``; return the assimilated permanent or ``None``.

    A battlefield permanent is taken (701.72a); a permanent card anywhere else is put onto the battlefield under
    the player's control with the counter already on it (701.72b: it is a Borg artifact creature from entry, so the
    type change is stamped for the visit it is about to start). An instant or sorcery card cannot be put onto the
    battlefield, so the action does nothing (fail closed).
    """
    state = engine.state
    if obj is None or state.player_by_id(controller_id).has_lost:  # RULE 800.4b
        return None
    from .control import gain_control

    if obj.zone == Zone.BATTLEFIELD:
        visit = obj.zone_incarnation
        previous_controller = obj.controller_id
        if not gain_control(state, obj, controller_id):
            return None
        if previous_controller != controller_id:
            # RULE 506.4: a permanent that changes controllers leaves combat.
            from .effects.attachments_transforms import TapEffect
            TapEffect._remove_from_combat(SimpleNamespace(state=state), obj)
        engine.add_counters(obj, ASSIMILATE_COUNTER_COUNT, ASSIMILATE_COUNTER_KIND, source=source)
        ability = _borg_type_change(state, obj, visit, source, controller_id)
    else:
        if obj.zone in (Zone.STACK, Zone.COMMAND) or not card_query.is_permanent_card(obj.card):
            return None
        # RULE 400.7: entering is one zone change, so the new battlefield visit is the next incarnation.
        visit = obj.zone_incarnation + 1
        ability = _borg_type_change(state, obj, visit, source, controller_id)
        engine.return_from_graveyard(
            obj, "battlefield", controller_id=controller_id,
            entry_counters={ASSIMILATE_COUNTER_KIND: ASSIMILATE_COUNTER_COUNT},
        )
        if obj.zone != Zone.BATTLEFIELD:
            # A replacement sent it elsewhere or its entry is still pending: no assimilated permanent to link. The
            # stamp pins a visit that never starts, so it can never apply to anything else.
            return None
        if obj.zone_incarnation != visit:
            visit = obj.zone_incarnation
            ability.params["object_incarnations"] = {obj.instance_id: visit}
    if source is not None:
        key = (source.instance_id, source.zone_incarnation if source_incarnation is None else source_incarnation)
        state.assimilated_visits.setdefault(key, []).append((obj.instance_id, visit))
    from . import continuous  # function-scoped: continuous imports the effects package that imports this module
    continuous.recompute(state)  # RULE 613.1: the new type, counter and controller apply at once
    return obj
