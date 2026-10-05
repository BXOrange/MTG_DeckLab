from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wizened_mentor() -> list[AbilitySpec]:
    """Whenever an opponent activates an ability of a permanent that isn't a mana ability, you create a 1/1 white Zombie creature token. This ability triggers only once each turn.

    — PLAY-ALL Step 2 (Eternal Might). Runic Armasaur's `ACTIVATED_ABILITY` head (mana abilities never reach that
    event) scoped to any permanent, with the trigger's own once-per-turn ``limit`` (RULE 603.2).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Zombie"],
                "token_name": "Zombie",
            })],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "not_you"},
                "limit": True,
            },
        ),
    ]


register("Wizened Mentor", _wizened_mentor)
