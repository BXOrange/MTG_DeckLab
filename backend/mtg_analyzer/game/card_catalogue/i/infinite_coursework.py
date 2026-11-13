from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _infinite_coursework() -> list[AbilitySpec]:
    """Enchant creature
    When this Aura enters, tap enchanted creature. It becomes unprepared.
    Enchanted creature loses all abilities and doesn't untap during its controller's untap step.

    Ability removal uses layer 6 (RULE 613.1f); the independent untap
    restriction remains a static of the Aura, not of the stripped host.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {"target_kind": "attached_permanent", "untap": False}),
                EffectSpec("become_unprepared", {"previous_subject": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec("static", [
            EffectSpec("remove_all_abilities", {"affects": "attached_permanent"}),
            EffectSpec("no_untap", {"affects": "attached_permanent"}),
        ]),
    ]


register("Infinite Coursework", _infinite_coursework)
