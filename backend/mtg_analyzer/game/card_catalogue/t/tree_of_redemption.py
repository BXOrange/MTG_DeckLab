from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tree_of_redemption() -> list[AbilitySpec]:
    """Defender
    {T}: Exchange your life total with this creature's toughness.

    — PLAY-ALL (Abzan Armor). Defender is a keyword. Tree of Perdition's `exchange_life_total_with_toughness` with
    ``player: you`` (no target): your life becomes its former toughness by an ordinary gain or loss, and its base toughness
    becomes your former life total through a permanent toughness-only layer-7b set.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_life_total_with_toughness", {"player": "you"})],
            cost={"text": "{T}"},
        ),
    ]


register("Tree of Redemption", _tree_of_redemption)
