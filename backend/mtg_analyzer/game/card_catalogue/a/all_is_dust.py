from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _all_is_dust() -> list[AbilitySpec]:
    """Each player sacrifices all permanents they control that are one or more colors.

    — Keen Engineering deck batch. The `sacrifice` edict over ``each_player`` with the new
    ``colored`` permanent type and ``count="all"`` (every matching permanent, so there is nothing to
    choose and no prompt) — a real sacrifice, so sacrifice triggers and RULE 701.17 apply.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("sacrifice", {
            "what": "colored", "count": "all", "selector": "each_player",
        })]),
    ]


register("All Is Dust", _all_is_dust)
