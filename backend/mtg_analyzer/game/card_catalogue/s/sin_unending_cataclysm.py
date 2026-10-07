from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sin_unending_cataclysm() -> list[AbilitySpec]:
    """Flying, trample
    As Sin enters, remove all counters from any number of artifacts, creatures, and enchantments. Sin enters with X +1/+1 counters on it, where X is twice the number of counters removed this way.
    When Sin dies, put its counters on target creature you control, then shuffle this card into its owner's library.

    — PLAY-ALL (Counter Blitz). Before entry, choose any number of
    artifacts, creatures and enchantments under any controller. Only after
    selection ends are their counters removed together. Twice the removed
    count is staged as entry counters; the death trigger transfers counters
    and shuffles Sin into its owner's library.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("entry_effect", {"effects": [
                {"type": "choose_objects", "params": {
                    "action": "select_only", "what": "permanent", "count": "all", "optional": True,
                    "pool_player_selector": "all",
                    "card_types_any": ["artifact", "creature", "enchantment"],
                    "prompt": "Permanents auswählen, deren Marken entfernt werden",
                    "then": [
                        {"type": "remove_counters", "params": {"previous_subject": True}},
                        {"type": "add_entry_counters", "params": {
                            "kind": "+1/+1", "amount": {
                                "kind": "this_way", "tally": "counters_removed_this_way", "multiply": 2,
                            },
                        }},
                    ],
                }},
            ]})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("transfer_event_counters", {"target_kind": "creature_you_control"}),
                EffectSpec("shuffle_self_into_library", {}),
            ],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Sin, Unending Cataclysm", _sin_unending_cataclysm)
