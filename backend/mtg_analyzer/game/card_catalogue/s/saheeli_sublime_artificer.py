from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _saheeli_sublime_artificer() -> list[AbilitySpec]:
    """Whenever you cast a noncreature spell, create a 1/1 colorless Servo artifact creature token.
    −2: Target artifact you control becomes a copy of another target artifact or creature you control until end of turn, except it's an artifact in addition to its other types.

    — PLAY-ALL (Living Energy). The Servo trigger is the parser's. The −2 is the new two-target
    `become_copy_of_target_until_eot` (``extra_target_specs``: the copier and "another" artifact or creature to copy).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": [], "subtypes": ["Servo"],
                "keywords": [], "is_artifact": True, "token_name": "Servo",
            })],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_filter": {"without_card_type": "creature"},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("become_copy_of_target_until_eot", {"add_types": ["Artifact"]})],
            cost={"loyalty": -2},
        ),
    ]


register("Saheeli, Sublime Artificer", _saheeli_sublime_artificer)
