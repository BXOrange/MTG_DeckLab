from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kenriths_transformation() -> list[AbilitySpec]:
    """Enchant creature
    When this Aura enters, draw a card.
    Enchanted creature loses all abilities and is a green Elk creature
    with base power and toughness 3/3.

    — MEC-43 round 2, the "Elk" template (Oko, Thief of Crowns' +1 shares
    the same clause but needs its own resolve-time `grant_until` wiring
    plus its other two loyalty abilities — a bigger lift left open).
    "Enchant creature"/the attach itself comes from the RULE 702 keyword
    catalogue, unaffected by hand-authoring. **Documented simplification**:
    only the creature type is *added* (`type_change`'s ``add_types``), the
    permanent's other printed card types aren't stripped — `Card.
    is_artifact`/``is_enchantment`` read the printed card directly, not a
    layer-4-aware property (`GameObject.is_land`'s own docstring already
    flags this as a gap worth extending, not yet done) — low practical
    impact, since the Elk has no abilities left to use any type distinction.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("remove_all_abilities", {"affects": "attached_permanent"}),
                EffectSpec("type_change", {
                    "affects": "attached_permanent", "add_types": ["creature"],
                    "set_subtypes": ["Elk"], "power": 3, "toughness": 3,
                }),
                EffectSpec("color_change", {"affects": "attached_permanent", "colors": ["G"], "set": True}),
            ],
        ),
    ]


register("Kenrith's Transformation", _kenriths_transformation)
