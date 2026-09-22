from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _doomsday() -> list[AbilitySpec]:
    """Search your library and graveyard for five cards and exile the
    rest. Put the chosen cards on top of your library in any order. You
    lose half your life, rounded up.

    — MEC-37. The original ticket framing ("exile up to five cards in a
    pile") turned out to describe a mechanic Doomsday doesn't actually
    have — its real printed text needed no new search primitive at all,
    only a re-check against the real oracle text: `SearchLibraryEffect`
    already supports `zones=["library", "graveyard"]` (combined-zone
    search), `exile_rest` (its own docstring already says
    "…Doomsday-shaped", built with this exact card in mind but never
    reached before now), and `destination="library_top"` — and since a
    multi-card `library_top` search already offers its picks one at a
    time and stacks each new pick *above* the last, the player already
    has full control over the final order simply by choosing which card
    to name each round (name the card that should be drawn last first,
    the one that should be drawn first last) — RULE 601.2c's "in any
    order" falls out for free. The lose-life half is a `bind` over the
    controller's life total halved, rounded up (RULE 107.3).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": "",
                    "destination": "library_top",
                    "count": 5,
                    "optional": False,
                    "zones": ["library", "graveyard"],
                    "exile_rest": True,
                }),
                EffectSpec("bind", {
                    "name": "half",
                    "amount": {"kind": "resource", "resource": "life", "divide": 2, "round_up": True},
                    "effects": [{"type": "lose_life", "params": {"amount": "$half"}}],
                }),
            ],
        ),
    ]


register("Doomsday", _doomsday)
