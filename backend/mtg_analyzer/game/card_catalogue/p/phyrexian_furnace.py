from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _phyrexian_furnace() -> list[AbilitySpec]:
    """{T}: Exile the bottom card of target player's graveyard.
    {1}, Sacrifice this artifact: Exile target card from a graveyard. Draw a
    card.

    — PLAY-ALL Step 2 (Oops! All Night's Whispers). The sacrifice ability is the
    parser's own claim, reproduced. The tap ability is the new
    `exile_bottom_graveyard_card` (a *player* target; the bottom card is the oldest,
    `graveyard[0]`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exile_bottom_graveyard_card", {"target_kind": "player"})],
            cost={"text": "{T}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("exile", {"target_kind": "any_graveyard_card"}), EffectSpec("draw", {"count": 1})],
            cost={"text": "{1}, sacrifice ~"},
        ),
    ]


register("Phyrexian Furnace", _phyrexian_furnace)
