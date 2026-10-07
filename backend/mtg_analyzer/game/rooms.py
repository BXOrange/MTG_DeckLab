"""Rooms: split permanents with two doors (RULE 709.5, MEC-111).

A Room card is a split card with a *shared* type line ("Enchantment — Room",
RULE 709.5a). On the stack it is just the half that was cast (RULE 709.3);
on the battlefield it is one permanent holding **both** halves, each of which
is *locked* until the permanent has the matching ``unlocked`` designation
(RULE 709.5c) — a locked half contributes no name, mana cost or rules text.

Model:

* ``Card`` already stores both halves (the front fields are the left half,
  ``back_*`` the right one — `Card.back_face`), so nothing here touches the
  card schema; the helpers below read it.
* ``GameObject.unlocked_doors`` is the set of designations (``"left"`` /
  ``"right"``).
* The permanent's **abilities are bound only for unlocked doors** — a lock
  removes them again — so no per-ability gating exists anywhere else in the
  engine: a locked door simply has no triggers/statics/replacements. Each
  bound ability is tagged with its ``door`` and remembered in
  ``GameObject.door_abilities`` so a lock can take exactly those back.
* ``GameState.add_to_battlefield`` is the single entry point
  (`prepare_entry`/`complete_entry`): casting the left half gives the left
  designation, casting the right half the right one (RULE 709.5d), anything
  else enters with neither.
* ``DOOR_UNLOCKED`` fires for every designation given, entering or not
  (RULE 709.5h); ``ROOM_FULLY_UNLOCKED`` when the second one arrives
  (RULE 709.5i).

A copy of a Room permanent copies both halves but not the designations
(they are not copiable values), so it has no abilities until a door is
unlocked — which falls out of `bind_from_catalogue` binding nothing for a
Room whose ``unlocked_doors`` is empty.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Optional

from ..models.cards.card import Card
from ..models.game.events import EventType, GameEvent
from ..models.mana.mana_cost import ManaCost
from ..parser.oracle.catalogue.player_event_head import THIS_DOOR
from ..parser.oracle.spec import AbilitySpec

if TYPE_CHECKING:  # models/ never imports game/ at load time; this is the reverse direction
    from ..models.game.game_object import GameObject
    from ..models.game.game_state import GameState

LEFT = "left"
RIGHT = "right"
DOORS = (LEFT, RIGHT)

#: The `GameObject` ability lists a bound door can populate; a lock takes its abilities back out of these.
_ABILITY_LISTS = ("triggered_abilities", "activated_abilities", "static_effects", "replacement_effects")

#: The front half's separator in a split card's printed name ("Left // Right").
_NAME_SEPARATOR = "//"


def is_room(card: Any) -> bool:
    """Whether ``card`` is a Room — a split card whose shared type line has the Room subtype
    (RULE 709.5). True for the whole card and for either half taken alone."""
    return (
        getattr(card, "layout", "") == "split"
        and "room" in str(getattr(card, "type_line", "")).lower().split("—")[-1].split()
    )


def has_doors(card: Any) -> bool:
    """Whether ``card`` is the *whole* Room (both halves known), as opposed to one half on the stack."""
    return is_room(card) and bool(getattr(card, "back_name", ""))


def front_name(card: Card) -> str:
    """The left half's own name (a split card's printed name is ``"Left // Right"``)."""
    return card.name.split(_NAME_SEPARATOR)[0].strip()


def door_card(card: Card, door: str) -> Optional[Card]:
    """One half of a Room as its own `Card` (the characteristics it has while that door is
    unlocked), or ``None`` for a card that is not a whole Room."""
    if not has_doors(card):
        return None
    if door == RIGHT:
        return card.back_face()
    cost = card.mana_cost_string
    return Card(
        id=card.id,
        name=front_name(card),
        type_line=card.type_line,
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        color_identity=set(card.color_identity),
        oracle_text=card.oracle_text,
        is_legendary=card.is_legendary,
        layout=card.layout,
        image_uri_small=card.image_uri_small,
        image_uri_normal=card.image_uri_normal,
        image_uri_large=card.image_uri_large,
        image_uri_png=card.image_uri_png,
    )


def door_name(card: Card, door: str) -> str:
    return card.back_name if door == RIGHT else front_name(card)


def door_cost(card: Card, door: str) -> ManaCost:
    """The mana cost of a half — what unlocking it costs (RULE 709.5e) when it is locked."""
    return ManaCost.parse(card.back_mana_cost_string if door == RIGHT else card.mana_cost_string)


def door_specs(card: Card, door: str) -> list[AbilitySpec]:
    """The abilities of one half, bound as if that half were the whole card, with each
    "this door" trigger scoped to ``door``."""
    from .card_registry import specs_for  # function-scoped: the registry imports the binder

    half = door_card(card, door)
    if half is None:
        return []
    return [_scope_to_door(spec, door) for spec in specs_for(half)]


def _scope_to_door(spec: AbilitySpec, door: str) -> AbilitySpec:
    """``spec`` with every ``{"door": "this"}`` trigger filter resolved to ``door``."""
    trigger = spec.trigger
    if not trigger or (trigger.get("filter") or {}).get("door") != THIS_DOOR:
        return spec
    return dataclasses.replace(spec, trigger={**trigger, "filter": {**trigger["filter"], "door": door}})


def locked_doors(obj: "GameObject") -> list[str]:
    """The doors of ``obj`` still locked, left first (empty for anything but a whole Room)."""
    if not has_doors(obj.card):
        return []
    return [door for door in DOORS if door not in obj.unlocked_doors]


def unlocked_door_names(obj: "GameObject") -> list[str]:
    """The names of ``obj``'s unlocked halves — what a Room permanent is called (RULE 709.5)."""
    if not has_doors(obj.card):
        return []
    return [door_name(obj.card, door) for door in DOORS if door in obj.unlocked_doors]


def bind_door(obj: "GameObject", door: str) -> None:
    """Give ``obj`` the abilities of ``door`` (idempotent), remembering which ones they are."""
    from .binding.core import attach_to_object  # function-scoped: the binder imports the registry

    if door in obj.door_abilities:
        return
    before = {name: list(getattr(obj, name)) for name in _ABILITY_LISTS}
    attach_to_object(obj, door_specs(obj.card, door))
    added: list[tuple[str, Any]] = []
    for name in _ABILITY_LISTS:
        known = {id(item) for item in before[name]}
        for item in getattr(obj, name):
            if id(item) not in known:
                item.door = door
                added.append((name, item))
    obj.door_abilities[door] = added
    # The binder describes every ability by the card's own (front) text; an ability of this door is described by the
    # door's — what a trigger-mode prompt or the stack shows for it.
    own_text, whole_text = door_card(obj.card, door).oracle_text, obj.card.oracle_text
    for _name, item in added:
        if getattr(item, "description", None) == whole_text:
            item.description = own_text


def unbind_door(obj: "GameObject", door: str) -> None:
    """Take back exactly the abilities `bind_door` gave for ``door``."""
    for name, item in obj.door_abilities.pop(door, []):
        items = getattr(obj, name)
        items[:] = [existing for existing in items if existing is not item]


def rebind_doors(obj: "GameObject") -> None:
    """Rebuild ``obj``'s door abilities from its designations — what `bind_from_catalogue`
    does for a Room (RULE 709.5: only unlocked halves have rules text)."""
    for door in list(obj.door_abilities):
        unbind_door(obj, door)
    for door in DOORS:
        if door in obj.unlocked_doors:
            bind_door(obj, door)


def clear_designations(obj: "GameObject") -> None:
    """RULE 400.7: a new object has neither designation and none of the abilities they gave."""
    for door in list(obj.door_abilities):
        unbind_door(obj, door)
    obj.unlocked_doors = set()


def set_designations(obj: "GameObject", doors: Any) -> None:
    """Give ``obj`` exactly the ``doors`` designations, rebinding its abilities — no events, no cost. For restoring a saved
    position (Replay import) and the Replay editor's door toggle; play itself goes through `unlock`/`lock`."""
    obj.unlocked_doors = {door for door in (doors or ()) if door in DOORS} if has_doors(obj.card) else set()
    rebind_doors(obj)


def entry_door(obj: "GameObject", from_stack: bool) -> Optional[str]:
    """RULE 709.5d: which half's designation ``obj`` enters with — the one that was cast, so
    the left for a whole-card cast and the right when the object is currently the right half
    (`GameEngine.cast_spell(face="back")` swaps ``obj.card`` to it). A token (a copy) was not
    cast, and neither was anything put onto the battlefield from another zone."""
    if obj.is_token or not from_stack or not is_room(obj.card):
        return None
    return LEFT if has_doors(obj.card) else RIGHT


def prepare_entry(obj: "GameObject", from_stack: bool) -> Optional[str]:
    """Before ``obj`` joins the battlefield: make it the whole Room (a right-half cast switched
    ``obj.card`` to that half) with no stale designations, and return the door it was cast as."""
    if not is_room(obj.card):
        return None
    door = entry_door(obj, from_stack)
    clear_designations(obj)
    front = obj._front_card
    if not has_doors(obj.card) and has_doors(front):
        obj.card = front
    return door


def complete_entry(state: "GameState", obj: "GameObject", door: Optional[str]) -> None:
    """After ``obj`` is on the battlefield: give it the designation it was cast with (RULE 709.5d)."""
    if door is not None and has_doors(obj.card):
        unlock(state, obj, door)


def unlock(state: "GameState", obj: "GameObject", door: str) -> bool:
    """RULE 709.5f: give ``obj`` the ``door`` designation. ``False`` if it already had it
    (or ``obj`` is not a Room with that door). Fires ``DOOR_UNLOCKED`` (RULE 709.5h) and, when
    this completes the pair, ``ROOM_FULLY_UNLOCKED`` (RULE 709.5i)."""
    if door not in DOORS or not has_doors(obj.card) or door in obj.unlocked_doors:
        return False
    obj.unlocked_doors.add(door)
    bind_door(obj, door)
    common = dict(
        instance_id=obj.instance_id,
        controller_id=obj.controller_id,
        player_id=obj.controller_id,
        object=obj.name,
        object_types=sorted(obj.type_words),
    )
    state.fire_event(GameEvent(EventType.DOOR_UNLOCKED, door=door, door_name=door_name(obj.card, door), **common))
    if len(obj.unlocked_doors) == len(DOORS):
        state.fire_event(GameEvent(EventType.ROOM_FULLY_UNLOCKED, **common))
    return True


def lock(state: "GameState", obj: "GameObject", door: str) -> bool:
    """RULE 709.5g: remove the ``door`` designation (and with it that half's abilities)."""
    if door not in obj.unlocked_doors:
        return False
    obj.unlocked_doors.discard(door)
    unbind_door(obj, door)
    return True
