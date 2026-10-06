from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _into_the_pit() -> list[AbilitySpec]:
    """You may look at the top card of your library any time.
    You may cast spells from the top of your library by sacrificing a nonland permanent in addition to paying their other costs.

    — PLAY-ALL (Death Toll). Two `top_library_permission` statics (Future Sight's shape): the look, and the cast with the new
    ``sacrifice_type`` — every cast through this grant also sacrifices a nonland permanent (RULE 601.2b/601.2h, paid alongside the
    mana cost; `GameEngine._top_library_sacrifice_victim`). **Simplification**: if the spell has its own sacrifice additional cost the
    two are not forced onto distinct permanents.
    """
    return [
        AbilitySpec("static", [EffectSpec("top_library_permission", {"look": True})]),
        AbilitySpec("static", [EffectSpec("top_library_permission", {"cast_spells": True, "sacrifice_type": "nonland_permanent"})]),
    ]


register("Into the Pit", _into_the_pit)
