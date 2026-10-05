from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mindblade_render() -> list[AbilitySpec]:
    """Whenever your opponents are dealt combat damage, if any of that damage was dealt by a Warrior, you draw a card and you lose 1 life.

    — Mindblade Render. Nelly Borca's per-step opponents batch (``opponents_batch``: one trigger however many
    opponents were hit, RULE 603.2c) with a Warrior filter on the damage sources — any controller's Warriors,
    as printed, so the group condition carries no ``controller``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1}), EffectSpec("lose_life", {"amount": 1})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {
                    "subject": "group", "other": False,
                    "filter": {"subtype": "warrior"}, "recipient_is_opponent": True,
                },
                "contributors": {"min": 1},
                "opponents_batch": True,
            },
        )
    ]


register("Mindblade Render", _mindblade_render)
