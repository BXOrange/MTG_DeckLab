from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _uba_mask() -> list[AbilitySpec]:
    """If a player would draw a card, that player exiles that card face up
    instead.
    Each player may play lands and cast spells from among cards they
    exiled with ~ this turn.

    — MEC-43. One replacement effect (`draw_exile_face_up`) covers both
    printed lines: it performs the exile itself and stamps `GameState.
    temp_play_permissions` on the exiled card in the same step, so the
    second line is a consequence of the first rather than a separate
    clause — the same "castable/playable from exile this turn" marker
    every other temp-exile-permission card already reads from `can_cast`/
    `can_play_land`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("draw_exile_face_up", {})],
        ),
    ]


register("Uba Mask", _uba_mask)
