from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _zo_zu_the_punisher() -> list[AbilitySpec]:
    """Whenever a land enters, Zo-Zu deals 2 damage to that land's
    controller. — Zo-Zu the Punisher. Named-by-proper-noun self-reference
    (not "this creature"/"~"), which `normalize._fold_self_reference`
    doesn't fold for a hyphenated card name — hand-authored rather than
    chasing that edge case for one card. New `DealDamageEffect`
    ``selector="event_controller"`` (the entering land's own controller,
    distinct from ``"event_player"``'s cast/draw-shaped "acting player").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_controller"})],
            trigger={
                "event": "ENTERS_BATTLEFIELD",
                "condition": {"subject": "group", "type": "land"},
            },
        )
    ]


register("Zo-Zu the Punisher", _zo_zu_the_punisher)
