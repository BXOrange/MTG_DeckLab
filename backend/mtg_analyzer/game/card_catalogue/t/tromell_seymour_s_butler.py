from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tromell_seymour_s_butler() -> list[AbilitySpec]:
    """Each other nontoken creature you control enters with an additional +1/+1 counter on it.
    {1}, {T}: Proliferate X times, where X is the number of nontoken creatures you control that entered this turn.

    — PLAY-ALL (Counter Blitz). The static is the parser's `extra_etb_counter` claim. The activation `bind`s the existing
    ``nontoken_creatures_you_entered_this_turn`` count selector into `proliferate`'s ``times``.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("extra_etb_counter", {"kind": "+1/+1", "count": 1, "filter": {"nontoken": True}, "other": True})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("bind", {
                "name": "n", "amount": {"kind": "count_selector", "selector": "nontoken_creatures_you_entered_this_turn"},
                "effects": [{"type": "proliferate", "params": {"times": "$n"}}],
            })],
            cost={"text": "{1}, {T}"},
        ),
    ]


register("Tromell, Seymour's Butler", _tromell_seymour_s_butler)
