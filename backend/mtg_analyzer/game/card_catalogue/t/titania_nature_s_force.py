from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _titania_nature_s_force() -> list[AbilitySpec]:
    """You may play Forests from your graveyard.
    Whenever a Forest you control enters, create a 5/3 green Elemental creature token.
    Whenever an Elemental you control dies, you may mill three cards.

    — PLAY-ALL (Death Toll). The two triggers are the parser's. The permission is the standing `graveyard_cast_permission` with Kethis's
    ``plays_lands`` widening (now also readable on the standing form): a land matching ``spell_criteria`` (type Forest) in your graveyard
    can be played, as often as your land drops allow.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_cast_permission", {
                "permanent_only": False, "once_per_turn": False, "plays_lands": True, "spell_criteria": {"type": "Forest"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 5, "toughness": 3, "colors": ["G"], "subtypes": ["Elemental"], "keywords": [], "token_name": "Elemental",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False, "subtypes": ["forest"], "nontoken": False,
            }},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("mill", {"count": 3})],
            trigger={"event": EventType.DIES, "condition": {
                "subject": "group", "controller": "you", "other": False, "subtypes": ["elemental"], "nontoken": False,
            }},
            optional=True,
        ),
    ]


register("Titania, Nature's Force", _titania_nature_s_force)
