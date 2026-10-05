from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _raging_ravine() -> list[AbilitySpec]:
    """Raging Ravine's animation and its self-attack growth trigger.

    Entering tapped and the two-colour mana ability are parsed from the card
    itself.  The colour layer of the animation is not represented by this
    engine yet, but the creature type, base P/T, and attack counter are.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {"type": "type_change", "params": {
                    "add_types": ["creature"], "add_subtypes": ["Elemental"],
                    "power": 3, "toughness": 3,
                }},
            })],
            cost={"mana": "{2}{R}{G}"},
        ),
        AbilitySpec(
            "triggered", [EffectSpec("add_counters", {"amount": 1, "kind": "+1/+1", "target_kind": None})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Raging Ravine", _raging_ravine)
