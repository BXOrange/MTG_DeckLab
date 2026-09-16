from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _intuition() -> list[AbilitySpec]:
    """Search your library for three cards and reveal them. Target
    opponent chooses one. Put that card into your hand and the rest into
    your graveyard. Then shuffle.

    — Vivi B4 batch. `IntuitionEffect`/`RulesEngine._request_intuition` —
    a genuinely two-player interactive search (the caster picks the three
    cards, then the *targeted opponent* picks which one is kept), self-
    contained rather than composed from `_request_search` (whose single
    ``destination`` has no way to hand off to a second player's choice).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("intuition_search", {"count": 3})],
        ),
    ]


register("Intuition", _intuition)
