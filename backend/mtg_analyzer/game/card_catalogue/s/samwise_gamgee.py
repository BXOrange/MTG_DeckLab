from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _samwise_gamgee() -> list[AbilitySpec]:
    """Whenever another nontoken creature you control enters, create a
    Food token.
    Sacrifice three Foods: Return target historic card from your
    graveyard to your hand. (Artifacts, legendaries, and Sagas are
    historic.)

    Simplified: "historic" isn't a modeled target filter — widened to
    "target card in your graveyard" (`graveyard_card`), the closest
    already-supported graveyard-target shape; likewise "nontoken" isn't
    enforced on a bare main-type group condition (only on a subtype-
    filtered one), so this also fires for a token creature entering.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "creature",
                    "controller": "you", "other": True,
                },
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_card", "destination": "hand"})],
            cost={"sacrifice_count": (3, "food")},
        ),
    ]


register("Samwise Gamgee", _samwise_gamgee)
