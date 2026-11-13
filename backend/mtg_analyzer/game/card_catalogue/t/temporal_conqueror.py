from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _temporal_conqueror() -> list[AbilitySpec]:
    """When this creature enters, mill three cards. Then return a land card from your graveyard to your hand. If you can't, create a Treasure token. (To mill three cards, put the top three cards from your library into your graveyard.)

    RULE 701.17a/608.2c: the mandatory return considers the graveyard after
    the mill; with no land card in it the choice has no pool and the
    ``else_effects`` tail ("If you can't") creates the Treasure instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("mill", {"count": 3}),
                EffectSpec("choose_objects", {
                    "action": "return_from_graveyard_to_hand", "what": "permanent", "pool_zone": "graveyard",
                    "permanent_filter": {"card_type": "land"}, "count": 1, "optional": False,
                    "else_effects": [{"type": "create_token", "params": {"count": 1, "token_name": "Treasure"}}],
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Temporal Conqueror", _temporal_conqueror)
