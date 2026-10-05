from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _graaz_unstoppable_juggernaut() -> list[AbilitySpec]:
    """Juggernauts you control attack each combat if able.
    Juggernauts you control can't be blocked by Walls.
    Other creatures you control have base power and toughness 5/3 and are Juggernauts in addition to
    their other creature types.

    — Keen Engineering deck batch. The first two lines are the synthetic ``attacks_if_able`` flag
    (Goblin Rabblemaster's grant) and a ``combat_restriction`` ``cant_be_blocked_by`` Walls, each over
    the *Juggernaut* group; the third is a layer-4 `type_change` (Juggernaut added, base 5/3) over
    the other creatures. Layer 4 resolves before layer 6, so the creatures it turns into Juggernauts
    are caught by the first two lines.
    """
    juggernauts = {"affects": "creatures_you_control", "subtype": "Juggernaut"}
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {**juggernauts, "keywords": ["attacks_if_able"]})]),
        AbilitySpec("static", [EffectSpec("combat_restriction", {
            **juggernauts, "kind": "cant_be_blocked_by", "filter": {"subtype": "Wall"},
        })]),
        AbilitySpec("static", [EffectSpec("type_change", {
            "affects": "other_creatures_you_control", "add_subtypes": ["Juggernaut"],
            "power": 5, "toughness": 3,
        })]),
    ]


register("Graaz, Unstoppable Juggernaut", _graaz_unstoppable_juggernaut)
