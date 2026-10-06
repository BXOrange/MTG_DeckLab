from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rendmaw_creaking_nest() -> list[AbilitySpec]:
    """Reach, menace
    When Rendmaw enters and whenever you play a card with two or more card types, each player creates a tapped 2/2 black Bird creature token with flying. The tokens are goaded for the rest of the game. (They attack each combat if able and attack a player other than you if able.)

    — PLAY-ALL (Death Toll). Reach and menace are keywords. One effect list (the ETB and the two "play a card" heads — a spell cast or a land
    played — share it): `create_token` with ``creators: each_player`` / ``tapped``, then `goad` of the ``created`` tokens ``permanent``ly
    (The Beamtown Bullies' referent). The new ``min_card_types`` trigger predicate counts the played card's distinct card types (RULE 205.2a).
    """
    def bodies() -> list[EffectSpec]:
        return [
            EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Bird"], "keywords": ["flying"],
                "token_name": "Bird", "creators": "each_player", "tapped": True,
            }),
            EffectSpec("goad", {"target_kind": None, "referent": "created", "permanent": True}),
        ]

    return [
        AbilitySpec("triggered", bodies(), trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}}),
        AbilitySpec("triggered", bodies(), trigger={
            "event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "min_card_types": 2,
        }),
        AbilitySpec("triggered", bodies(), trigger={
            "event": EventType.LAND_PLAYED, "condition": {"subject": "you"}, "min_card_types": 2,
        }),
    ]


register("Rendmaw, Creaking Nest", _rendmaw_creaking_nest)
