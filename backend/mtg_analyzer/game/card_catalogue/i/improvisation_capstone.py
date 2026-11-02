from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _improvisation_capstone() -> list[AbilitySpec]:
    """Exile cards from the top of your library until you exile cards with total mana value 4 or greater. You may cast any number of spells from among them without paying their mana costs.
    Paradigm (Then exile this spell. After you first resolve a spell with this name, you may cast a copy of it from exile without paying its mana cost at the beginning of each of your first main phases.)

    — Commander Cube singleton batch. The exile loop with a running mana-value total is `exile_until_total_mana_value`
    (`game/effects/exile_top_pool.py`). The free casting is the PAR-167 resolution-local window over the exiled pool
    (RULE 608.2g, any number of spells, RULE 118.9 free cast). Paradigm is the keyword catalogue's synthesized ability.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("seq", {"effects": [
            {"type": "exile_until_total_mana_value", "params": {"threshold": 4}},
            {"type": "cast_window_exiled_pool", "params": {
                "resolution_local": True, "any_number": True, "free": True, "only_spells": True,
            }},
        ]})]),
    ]


register("Improvisation Capstone", _improvisation_capstone)
