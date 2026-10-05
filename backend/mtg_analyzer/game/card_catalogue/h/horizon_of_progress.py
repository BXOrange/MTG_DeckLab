from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _horizon_of_progress() -> list[AbilitySpec]:
    """{T}, Pay 1 life: Add one mana of any type that a land you control
    could produce.
    {3}, {T}: You may put a land card from your hand onto the
    battlefield tapped.
    {1}, {T}, Sacrifice this land: Draw a card.

    — MEC-12 (cEDH M-K). The first ability needs no entry at all —
    `mana_abilities_for` reads "any type a land you control could
    produce" straight off oracle text, independent of catalogue
    registration (same reasoning as Treasure Vault's plain mana ability).
    The third is already parser-claimed for free (`reuse` confirms it —
    restated here since registering this name turns the parser fallback
    off for *every* ability, not just the unclaimed one). Only the second
    needs real hand-authoring: `put_from_hand_onto_battlefield`'s new
    ``tapped`` flag.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("put_from_hand_onto_battlefield", {
                "criteria": "Land", "count": 1, "tapped": True,
            })],
            cost={"text": "{3}, {T}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{1}, {T}, Sacrifice ~"},
        ),
    ]


register("Horizon of Progress", _horizon_of_progress)
