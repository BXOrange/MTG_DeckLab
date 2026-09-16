from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Killian, Decisive Mentor (Aura-enchanted-creature attack trigger)
# ===========================================================================
# Engine: `_build_group_ok` gained the ``enchanted_by_your_aura`` filter.


def _killian_decisive_mentor() -> list[AbilitySpec]:
    """Whenever an enchantment you control enters, tap up to one target
    creature and goad it.
    Whenever one or more creatures that are enchanted by an Aura you control
    attack, draw a card.

    The first ability folds in from the parser; only the attack trigger
    needs authoring. Modeled as a per-creature ATTACKS trigger capped once
    per turn (RULE 603.3b "one or more" aggregate)."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"target_kind": "creature", "optional": True}),
             EffectSpec("goad", {"target_kind": None})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "enchantment", "controller": "you",
                              "other": False},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ATTACKS,
                "condition": {"subject": "group", "controller": "you",
                              "enchanted_by_your_aura": True},
                "limit": True,
            },
        ),
    ]


register("Killian, Decisive Mentor", _killian_decisive_mentor)
