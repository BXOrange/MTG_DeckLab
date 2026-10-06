from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sin_unending_cataclysm() -> list[AbilitySpec]:
    """Flying, trample
    As Sin enters, remove all counters from any number of artifacts, creatures, and enchantments. Sin enters with X +1/+1 counters on it, where X is twice the number of counters removed this way.
    When Sin dies, put its counters on target creature you control, then shuffle this card into its owner's library.

    — PLAY-ALL (Counter Blitz). Flying and trample are keywords. The entry clause is the `enters_with_counters_count` static (`entry_counters_self`) with the new
    ``remove_counters_scope`` and ``multiplier`` 2 (`RulesEngine._apply_entry_counters`; **simplification:** "any number" is taken as every artifact, creature and
    enchantment). The dies trigger is `transfer_event_counters` (every kind from the dying Sin's RULE 603.10a snapshot onto a creature you control) then
    `shuffle_self_into_library`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("enters_with_counters_count", {
                "kind": "+1/+1", "remove_counters_scope": "artifacts_creatures_enchantments", "multiplier": 2,
            })],
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
