from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _raging_ravine() -> list[AbilitySpec]:
    """Raging Ravine's animation and its self-attack growth trigger.

    Entering tapped and the two-colour mana ability are parsed from the card
    itself.  The animation sets type, base P/T and colours (layer 5); the attack
    counter is a separate trigger.
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
            }),
             # RULE 613.4b: "red and green" replaces its colours (layer 5).
             EffectSpec("grant_until", {
                 "duration": "end_of_turn", "target_kind": None,
                 "static": {"type": "color_change", "params": {"colors": ["R", "G"], "set": True, "affects": "self"}},
             })],
            cost={"mana": "{2}{R}{G}"},
        ),
        AbilitySpec(
            "triggered", [EffectSpec("add_counters", {"amount": 1, "kind": "+1/+1", "target_kind": None})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Raging Ravine", _raging_ravine)
