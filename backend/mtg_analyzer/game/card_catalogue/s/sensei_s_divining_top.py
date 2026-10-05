from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _senseis_divining_top() -> list[AbilitySpec]:
    """{1}: Look at the top three cards of your library, then put them
    back in any order.
    {T}: Draw a card, then put this artifact on top of its owner's
    library.

    — Sensei's Divining Top. Its first ability is the shared `scry`
    non-interactive resolution (Ponder's own precedent — every legal "any
    order" outcome is already reachable); the second needs
    `ReturnToLibraryEffect`'s new self mode (``target_kind=None``, no
    RULE 115 target at all).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("scry", {"count": 3})],
            cost={"text": "{1}"},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("return_to_library", {"target_kind": None, "position": "top"}),
            ],
            cost={"taps_self": True},
        ),
    ]


register("Sensei's Divining Top", _senseis_divining_top)
