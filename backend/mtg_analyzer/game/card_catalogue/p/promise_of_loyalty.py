from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Promise of Loyalty (each player keeps one creature) — PAR-60
# ===========================================================================
# Pure reuse: `SacrificeEffect(selector="each_player", count="all_but_one")`
# is exactly "each player puts a vow counter on a creature they control and
# sacrifices the rest" minus the mark.


def _promise_of_loyalty() -> list[AbilitySpec]:
    """Each player puts a vow counter on a creature they control and
    sacrifices the rest. Each of those creatures can't attack you or
    planeswalkers you control for as long as it has a vow counter on it.

    Documented simplification: modeled as "each player sacrifices all
    creatures but one" (`SacrificeEffect` ``count="all_but_one"``); the vow
    counter on the kept creature and its "can't attack you" rider are
    dropped (no hook to mark the specific creature left behind by an
    interactive keep-one)."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("sacrifice", {"selector": "each_player", "what": "creature",
                                      "count": "all_but_one"})],
        ),
    ]


register("Promise of Loyalty", _promise_of_loyalty)
