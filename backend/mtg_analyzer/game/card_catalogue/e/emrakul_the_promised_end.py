from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _emrakul_the_promised_end() -> list[AbilitySpec]:
    """Whenever you cast a spell, target opponent gains control of Emrakul,
    the Promised End. You take an extra turn after this one.

    — MEC-51 (RULE 720), same `control_player` primitive as Mindslaver
    (`card_catalogue/m/mindslaver.py`), here on a self-triggered
    ``scope="turn", target_kind="opponent"`` grant with
    ``grant_extra_turn_after=True`` folding in the "take an extra turn"
    payoff.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("control_player", {
                "scope": "turn", "target_kind": "opponent",
                "grant_extra_turn_after": True,
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "self"}},
        ),
    ]


register("Emrakul, the Promised End", _emrakul_the_promised_end)
