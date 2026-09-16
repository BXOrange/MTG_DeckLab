from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _everlasting_torment() -> list[AbilitySpec]:
    """Players can't gain life.
    Damage can't be prevented.
    All damage is dealt as though its source had wither.

    Registered wholesale, so all three standing statics are authored:
    ``prevent_all_life_gain`` (already parser-claimed on its own),
    ``damage_cant_be_prevented`` (new marker static — RULE 615, consulted by
    `RulesEngine._run_replacement_loop`), and ``global_wither`` (new marker
    static — RULE 609.4b as-though, consulted by `RulesEngine.deal_damage`).
    """
    return [
        AbilitySpec("static", [EffectSpec("prevent_all_life_gain", {})]),
        AbilitySpec("static", [EffectSpec("damage_cant_be_prevented", {})]),
        AbilitySpec("static", [EffectSpec("global_wither", {})]),
    ]


register("Everlasting Torment", _everlasting_torment)
