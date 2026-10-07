from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "a 3/1 white Spirit creature token with flying" — the Eerie payoff, on both of its triggers.
_SPIRIT = {"count": 1, "power": 3, "toughness": 1, "colors": ["W"], "subtypes": ["Spirit"], "keywords": ["flying"], "token_name": "Spirit"}


def _ghostly_dancers() -> list[AbilitySpec]:
    """Flying
    When this creature enters, return an enchantment card from your graveyard to your hand or unlock a locked door of a Room you control.
    Eerie — Whenever an enchantment you control enters and whenever you fully unlock a Room, create a 3/1 white Spirit creature token with flying.

    — MEC-111. Flying is the keyword's. The enters trigger is a choose-one between the parser's graveyard return (a pick, not a target) and
    `unlock_door` (RULE 709.5f); the two Eerie heads are the parser's own, over one `create_token`.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_enchantment", "destination": "hand", "pick": True})],
                    [EffectSpec("unlock_door", {})],
                ],
                "descriptions": [
                    "Eine Verzauberungskarte aus deinem Friedhof auf die Hand nehmen.",
                    "Eine verriegelte Tür eines Raums unter deiner Kontrolle entriegeln.",
                ],
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", dict(_SPIRIT))],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "group", "controller": "you", "other": False, "type": "enchantment"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", dict(_SPIRIT))],
            trigger={"event": EventType.ROOM_FULLY_UNLOCKED, "condition": {"subject": "you"}},
        ),
    ]


register("Ghostly Dancers", _ghostly_dancers)
