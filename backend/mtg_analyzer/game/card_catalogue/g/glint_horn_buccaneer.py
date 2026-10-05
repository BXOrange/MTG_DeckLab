from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _glint_horn_buccaneer() -> list[AbilitySpec]:
    """Haste
    Whenever you discard a card, this creature deals 1 damage to each
    opponent.
    {1}{R}, Discard a card: Draw a card. Activate only if this creature
    is attacking.

    — MEC-12 (cEDH M-K). The new ``"DISCARD"`` row in `effect_binder.
    _GROUP_CONTROLLER_EVENT_KEYS` (a plain player-subject trigger,
    ``{"subject": "you"}`` — the same shape "whenever you scry/gain
    life/draw a card" already use, just missing this one event) closes
    the first ability; the second's "activate only if attacking" is
    already-general `ActivationCost.activation_condition` machinery
    (`static_conditions`' existing ``source_attacking`` kind, PAR-10) —
    no new primitive, just the first real card to combine the two. Haste
    is a printed keyword, recognized independently of this entry.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "each_opponent"})],
            trigger={"event": "DISCARD", "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={
                "mana": "{1}{R}", "discard": 1,
                "activation_condition": {"kind": "source_attacking"},
            },
        ),
    ]


register("Glint-Horn Buccaneer", _glint_horn_buccaneer)
