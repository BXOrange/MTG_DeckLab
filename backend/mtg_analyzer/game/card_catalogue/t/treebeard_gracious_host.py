from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _treebeard_gracious_host() -> list[AbilitySpec]:
    """Trample, ward {2}
    When Treebeard enters, create two Food tokens.
    Whenever you gain life, put that many +1/+1 counters on target
    Halfling or Treefolk.

    Simplified: the target is widened to "target creature you control"
    (no subtype-filtered RULE 115 target kind exists yet — every real
    target_kind is either broad main-type or a fixed single subtype, not
    an ad-hoc "Halfling or Treefolk" OR-list).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 2, "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "target_kind": "creature_you_control", "amount_from_trigger_event": "amount",
            })],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
    ]


register("Treebeard, Gracious Host", _treebeard_gracious_host)
