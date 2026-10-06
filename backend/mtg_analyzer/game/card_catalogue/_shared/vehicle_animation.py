"""Shared body for "target Vehicle becomes an artifact creature until end of turn" (Mech Hangar, Peacewalker Colossus, Mobilizer Mech)."""
from __future__ import annotations

from ....parser.oracle.spec import EffectSpec


def animate_vehicle(target_kind: str, optional: bool = False) -> EffectSpec:
    """RULE 301.7: the chosen Vehicle gains the creature type until end of turn (layer 4, `type_change`) with its own printed Vehicle P/T
    (``pt_selector: vehicle`` — that of whichever Vehicle was chosen)."""
    return EffectSpec("grant_until", {
        "static": {"type": "type_change", "params": {"add_types": ["creature"], "pt_selector": "vehicle"}},
        "duration": "end_of_turn", "target_kind": target_kind, "optional": optional, "count": 1,
    })
