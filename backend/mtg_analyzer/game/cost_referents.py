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

from typing import TYPE_CHECKING, Any, Iterable, Optional

from . import continuous

if TYPE_CHECKING:
    from ..models.game.game_object import GameObject

#: The verbs a cost can move an object with; the wording of "the <kind> card's ..." in oracle text.
COST_REFERENT_KINDS: tuple[str, ...] = ("discarded", "exiled", "tapped", "revealed", "sacrificed")
#: The stats a referent amount may read: the RULE 202.3 mana value, RULE 208.1 power / toughness, and the number of
#: RULE 205.2a card types the object had ("the number of card types the discarded card has", Mount Velus Manticore).
COST_REFERENT_STATS: tuple[str, ...] = ("mana_value", "power", "toughness", "card_types")
#: The selector prefix `continuous.count_selector` routes here.
COST_REFERENT_SELECTOR_PREFIX = "cost_referent_"


def referent_record(obj: "GameObject") -> dict[str, Any]:
    """``obj``'s characteristics right now -- call it *before* the cost moves the object (RULE 608.2h)."""
    return {
        "instance_id": obj.instance_id,
        "mana_value": int(obj.mana_value or 0),
        "power": int(obj.power or 0),
        "toughness": int(obj.toughness or 0),
        "card_types": len(continuous.card_types_of(obj)),
    }


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
