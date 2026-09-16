from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Immoral Bargain (sacrifice X creatures -> destroy X) — PAR-60
# ===========================================================================
# New `immoral_bargain` effect + a new ``destroy`` action for
# `_request_choose_objects` (the destroy sibling of ``sacrifice``). X is
# defined by the additional-cost sacrifice, resolved at resolution.


def _immoral_bargain() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice X creatures.
    Destroy X target nonland permanents."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("immoral_bargain", {})],
        ),
    ]


register("Immoral Bargain", _immoral_bargain)
