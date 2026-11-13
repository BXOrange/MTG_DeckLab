from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: Threshold (RULE 207.2c): the graveyard size that turns the ability on.
THRESHOLD_CARDS = 7


def _de_evolve() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets -4/-0, can't block, and is a Salamander. (It loses all other creature types.)
    Threshold — At the beginning of each upkeep, if there are seven or more cards in your graveyard, exile enchanted creature.

    RULE 205.1a / 205.3m: "is a Salamander" replaces the creature types
    (``set_creature_types``, layer 4), keeping non-creature subtypes.
    RULE 702.5: Enchant folds in from the keyword catalogue.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"power": -4, "toughness": 0, "affects": "attached_permanent"}),
                EffectSpec("grant_keyword", {"keywords": ["cant_block"], "affects": "attached_permanent"}),
                EffectSpec("type_change", {"affects": "attached_permanent", "set_creature_types": ["Salamander"]}),
            ],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "attached_permanent"}, condition={
                "kind": "control_count", "selector": "cards_in_your_graveyard", "min": THRESHOLD_CARDS,
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "active_if": {"kind": "control_count", "selector": "cards_in_your_graveyard", "min": THRESHOLD_CARDS},
            },
        ),
    ]


register("De-evolve", _de_evolve)
