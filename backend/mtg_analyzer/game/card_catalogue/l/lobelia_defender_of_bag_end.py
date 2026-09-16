from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lobelia_defender_of_bag_end() -> list[AbilitySpec]:
    """When Lobelia enters, look at the top card of each opponent's
    library and exile those cards face down.
    {T}, Sacrifice an artifact: Choose one — Until end of turn, you may
    play a card exiled with Lobelia without paying its mana cost. / Each
    opponent loses 2 life and you gain 2 life.

    Simplified: narrowed to the second mode only (each opponent loses 2
    life, you gain 2 life) — the ETB peek-and-exile plus "play what was
    exiled with ~" free-cast window needs a linked-exile-with-a-play-
    window primitive this engine doesn't have yet (`ExileEffect(remember=
    True)` links to *one* object, not a per-opponent set with its own
    later play permission).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("lose_life", {"amount": 2, "selector": "each_opponent"}), EffectSpec("gain_life", {"amount": 2})],
            cost={"taps_self": True, "sacrifice": "artifact"},
        ),
    ]


register("Lobelia, Defender of Bag End", _lobelia_defender_of_bag_end)
