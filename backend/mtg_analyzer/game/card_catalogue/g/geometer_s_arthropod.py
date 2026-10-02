from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _geometer_s_arthropod() -> list[AbilitySpec]:
    """Whenever you cast a spell with {X} in its mana cost, look at the top X
    cards of your library. Put one of them into your hand and the rest on the
    bottom of your library in a random order.

    — PLAY-ALL Step 2 (Hydranten). The trigger head is Elementalist's Palette's
    (`SPELL_CAST` by you + `spell_has_x`). The body is PAR-144's
    `inspect_top_choose` — the grammar refuses ``x``, so its ``count`` is an
    `x_paid` operand read off the cast spell (``of: trigger_subject`` — the
    spell on the stack still carries its announced X), one pick to hand, the rest
    to the bottom in random order.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("inspect_top_choose", {
                "count": {"kind": "x_paid", "of": "trigger_subject"},
                "action": "library_to_hand", "max_picks": 1,
                "rest_destination": "library_bottom_random",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_has_x": True,
            },
        ),
    ]


register("Geometer's Arthropod", _geometer_s_arthropod)
