from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Songbirds' Blessing (Aura attack-trigger dig) — PAR-60
# ===========================================================================
# Pure reuse: `dig_until` on an ``attached_permanent`` ATTACKS trigger.


def _songbirds_blessing() -> list[AbilitySpec]:
    """Enchant creature (folds in).
    Whenever enchanted creature attacks, reveal cards from the top of your
    library until you reveal an Aura card. You may put that card onto the
    battlefield. If you don't, put it into your hand. Put the rest on the
    bottom of your library in a random order.

    Documented simplification: the "you may put that card onto the
    battlefield" option is dropped (an Aura put onto the battlefield by an
    effect needs an enchant-target choice not wired for this dig) — the
    revealed Aura always goes to hand instead."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": {"type": "Aura"}, "hit_destination": "hand",
                "rest_destination": "library_bottom_random"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Songbirds' Blessing", _songbirds_blessing)
