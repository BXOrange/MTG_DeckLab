from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hologram_stalker() -> list[AbilitySpec]:
    """When this creature enters, return target permanent card from your graveyard to your hand.
    Whenever a card leaves your graveyard, create a 3/3 colorless Illusion artifact creature token. This ability triggers only once each turn.

    RULE 603.2 / 603.2g: as Vash, one trigger per card leaving, capped at once
    each turn. The ETB return itself removes a card from the graveyard, so
    the token is made on the same turn the creature enters.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_permanent", "destination": "hand"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 3, "toughness": 3, "colors": [], "subtypes": ["Illusion"],
                "is_artifact": True, "token_name": "Illusion",
            })],
            trigger={"event": EventType.CARD_LEFT_GRAVEYARD, "graveyard_owner": "you", "limit": True},
        ),
    ]


register("Hologram Stalker", _hologram_stalker)
