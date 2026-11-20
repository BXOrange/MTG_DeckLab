"""RULE 608.2h last-known information about the objects a cost moved.

An activated ability's cost or a spell's additional cost can discard, exile, tap, reveal or sacrifice objects whose
characteristics the resolving effect then measures ("where X is the discarded card's mana value", "the power of the
creature tapped this way", "the total power of the creatures sacrificed this way"). The object has changed zone (a
new object, RULE 400.7) or its characteristics may no longer be readable by the time the effect resolves, so the cost
snapshots them *as the cost moved them* onto the ability's source (the spell for a spell's additional cost).

One record structure serves every cost kind: ``source.cost_referents`` maps a kind (``COST_REFERENT_KINDS``) to the
records of the objects that kind of cost moved, in payment order. The records are plain dicts, so cloning a
`GameState` copies them with the object (clone / undo keep them). The amount side is
`continuous.count_selector`'s ``cost_referent_<kind>_<stat>`` family, which sums ``stat`` over a kind's records
(one record for "the discarded card", all of them for "the total power of the sacrificed creatures").
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterable, Iterator, Optional

from . import continuous

if TYPE_CHECKING:
    from ..models.game.game_object import GameObject

#: The verbs a cost can move an object with; the wording of "the <kind> card's ..." in oracle text.
COST_REFERENT_KINDS: tuple[str, ...] = ("discarded", "exiled", "tapped", "revealed", "sacrificed")
#: The stats a referent amount may read: the RULE 202.3 mana value, RULE 208.1 power / toughness, and the number of
#: RULE 205.2a card types the object had ("the number of card types the discarded card has", Mount Velus Manticore).
COST_REFERENT_STATS: tuple[str, ...] = (
    "mana_value", "power", "toughness", "card_types", "count",
    # MEC-169 "the creatures sacrificed this way": the same measures over the records that were creatures when they left
    # (a sacrificed Vehicle or artifact is no creature, so its power does not count).
    "creature_count", "creature_power", "creature_toughness", "creature_mana_value",
)
#: The selector prefix `continuous.count_selector` routes here.
COST_REFERENT_SELECTOR_PREFIX = "cost_referent_"


def referent_record(obj: "GameObject") -> dict[str, Any]:
    """``obj``'s characteristics right now -- call it *before* the cost moves the object (RULE 608.2h)."""
    record = {
        "instance_id": obj.instance_id,
        "mana_value": int(obj.mana_value or 0),
        "power": int(obj.power or 0),
        "toughness": int(obj.toughness or 0),
        "card_types": len(continuous.card_types_of(obj)),
        "count": 1,
    }
    if obj.is_creature:
        record.update(creature_count=1, creature_power=record["power"], creature_toughness=record["toughness"],
                      creature_mana_value=record["mana_value"])
    return record


def note_graveyard_visit(record: dict[str, Any], obj: "GameObject") -> None:
    """Remember the graveyard visit a cost's move created for ``obj`` (RULE 400.7: the card there is a new object), so
    "exile ~ and those creature cards" finds exactly the card the sacrifice put there -- nothing for a token or a card a
    replacement effect sent elsewhere."""
    from ..models.game.game_object import Zone

    if obj.zone == Zone.GRAVEYARD:
        record["graveyard_visit"] = obj.zone_incarnation


def snapshot_referents(objs: Iterable["GameObject"]) -> list[dict[str, Any]]:
    """The records of ``objs`` as they are now, to be stored once the cost has moved them (`store_referents`)."""
    return [referent_record(obj) for obj in objs]


def reset_referents(holder: Optional["GameObject"]) -> None:
    """A fresh payment forgets what an earlier one moved (a stale referent must not leak into the next activation)."""
    if holder is not None:
        holder.cost_referents = {}


def store_referents(holder: Optional["GameObject"], kind: str, records: list[dict[str, Any]]) -> None:
    """Append ``records`` to ``holder``'s ``kind`` referents."""
    if holder is None or not records:
        return
    if kind not in COST_REFERENT_KINDS:
        raise ValueError(f"unknown cost referent kind {kind!r}")
    holder.cost_referents.setdefault(kind, []).extend(records)


def referent_total(holder: Optional["GameObject"], kind: str, stat: str) -> int:
    """The sum of ``stat`` over ``holder``'s ``kind`` referents; ``0`` for none (the safe fallback every selector uses)."""
    if holder is None or stat not in COST_REFERENT_STATS:
        return 0
    return sum(int(record.get(stat, 0) or 0) for record in (getattr(holder, "cost_referents", None) or {}).get(kind, ()))


def parse_referent_selector(selector: str) -> Optional[tuple[str, str]]:
    """``"cost_referent_discarded_mana_value"`` -> ``("discarded", "mana_value")``; ``None`` for anything else."""
    if not selector.startswith(COST_REFERENT_SELECTOR_PREFIX):
        return None
    rest = selector[len(COST_REFERENT_SELECTOR_PREFIX):]
    for kind in COST_REFERENT_KINDS:
        if rest.startswith(kind + "_") and rest[len(kind) + 1:] in COST_REFERENT_STATS:
            return kind, rest[len(kind) + 1:]
    return None


#: The per-payment stamps an activated ability's cost leaves on its source for the effect to read (RULE 608.2h): the
#: records above and the older ``sacrificed_cost_*`` scalars. They live on the source permanent, so a second
#: activation paid while the first is still on the stack would overwrite them; each activation therefore takes a
#: snapshot onto its own `StackItem` (`snapshot_activation_stamps`) and resolution binds it back (`bound_to_resolution`).
ACTIVATION_COST_STAMPS: tuple[str, ...] = (
    "cost_referents", "sacrificed_cost_mana_value", "sacrificed_cost_power", "sacrificed_cost_toughness",
    "sacrificed_cost_words", "sacrificed_cost_was_suspected", "sacrificed_cost_counters",
    "sacrificed_cost_attached_ids", "sacrificed_cost_card_types", "sacrificed_cost_instance_id", "sacrificed_cost_count",
    "sacrificed_cost_copiable_card", "discarded_cost_card_types", "discarded_cost_words",
)
#: Stamps holding a `Card` (a large shared definition, never mutated): referenced, not deep-copied.
_SHARED_STAMPS = frozenset({"sacrificed_cost_copiable_card"})


def snapshot_activation_stamps(source: Any) -> dict[str, Any]:
    """``source``'s current cost stamps, copied for the `StackItem` of the activation that just paid them."""
    return {
        name: (getattr(source, name, None) if name in _SHARED_STAMPS else copy.deepcopy(getattr(source, name, None)))
        for name in ACTIVATION_COST_STAMPS
    }


@contextmanager
def bound_to_resolution(source: Any, stamps: Optional[dict[str, Any]]) -> Iterator[None]:
    """While one activated ability resolves, ``source`` carries that activation's own stamps, not a later one's."""
    if source is None or not stamps:
        yield
        return
    live = {name: getattr(source, name, None) for name in stamps}
    for name, value in stamps.items():
        setattr(source, name, value)
    try:
        yield
    finally:
        for name, value in live.items():
            setattr(source, name, value)
