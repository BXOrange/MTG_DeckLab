from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _forum_filibuster() -> list[AbilitySpec]:
    """At the beginning of your upkeep, create a 2/1 white and black Inkling
    creature token with flying. When you do, return up to one target Aura or
    Equipment card from your graveyard to the battlefield attached to that
    token.

    Documented simplification: the "attached to that token" placement of the
    returned Aura/Equipment is not modeled — it returns to the battlefield
    on its own (an Equipment stays unattached; an Aura with no legal object
    is put into the graveyard by SBA, a rare corner these decks don't lean
    on)."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": 1, "token_name": "Inkling", "power": 2, "toughness": 1,
                    "colors": ["W", "B"], "subtypes": ["Inkling"], "keywords": ["flying"],
                }),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_artifact_or_creature", "destination": "battlefield",
                    "optional": True,
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
        ),
    ]


register("Forum Filibuster", _forum_filibuster)
