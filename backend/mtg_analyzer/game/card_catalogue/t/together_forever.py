from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _together_forever() -> list[AbilitySpec]:
    """When this enchantment enters, support 2. (Put a +1/+1 counter on each of up to two target creatures.)
    {1}: Choose target creature with a counter on it. When that creature dies this turn, return that card to its owner's hand.

    — PLAY-ALL (Counter Blitz). Support is the parser's claim. The activation is Graceful Reprieve's `create_turn_trigger` (a DIES trigger scoped
    to the chosen creature, ``target_kind`` + the new ``creature_filter`` for "with a counter on it") whose body is the new
    `return_trigger_subject_to_hand` (the card the DIES event names goes from its owner's graveyard to their hand).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "+1/+1", "target_kind": "creature", "target_count": 2, "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_turn_trigger", {
                "trigger": {"event": "DIES", "condition": {"subject": "self"}},
                "effects": [{"type": "return_trigger_subject_to_hand", "params": {}}],
                "optional": False, "target_kind": "creature", "creature_filter": {"has_counter": True},
                "description": "when that creature dies this turn, return that card to its owner's hand.",
            })],
            cost={"mana": "{1}"},
        ),
    ]


register("Together Forever", _together_forever)
