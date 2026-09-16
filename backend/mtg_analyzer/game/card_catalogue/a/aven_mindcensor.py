from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aven_mindcensor() -> list[AbilitySpec]:
    """Flying
    If an opponent would search a library, that player searches the top
    four cards of that library instead.

    — MEC-12 (cEDH Rocco/staples/staples 2). Flying is already
    parser-claimed for free; the static half is the new
    `grant_search_limited_to_top_n` (RULE 701.19a-adjacent narrowing, not
    `grant_search_prohibited`'s outright block) — `RulesEngine.
    _search_zone_objects` scans for it exactly where `_request_search`
    already scans for the prohibition.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_search_limited_to_top_n", {"n": 4})],
        ),
    ]


register("Aven Mindcensor", _aven_mindcensor)
