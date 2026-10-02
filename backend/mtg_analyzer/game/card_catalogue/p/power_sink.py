from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _power_sink() -> list[AbilitySpec]:
    """Counter target spell unless its controller pays {X}. If that player
    doesn't, they tap all lands with mana abilities they control and lose all
    unspent mana.

    — PLAY-ALL Step 2 (Hydranten). `counter` with ``unless_pays: {X}`` (the
    announced X is read off the source at resolution) and the new
    ``tap_lands_empty_pool_if_unpaid``: on every branch that ends in the
    counter — the controller declines *or* cannot pay — `RulesEngine.
    _tap_lands_and_empty_pool` taps their untapped lands that have a mana
    ability (no mana is produced) and empties their mana pool. Paying the {X}
    leaves them untouched.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {"unless_pays": "{X}", "tap_lands_empty_pool_if_unpaid": True})],
        ),
    ]


register("Power Sink", _power_sink)
