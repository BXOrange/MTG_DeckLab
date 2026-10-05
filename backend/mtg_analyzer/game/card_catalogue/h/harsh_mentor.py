from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _harsh_mentor() -> list[AbilitySpec]:
    """Whenever an opponent activates an ability of an artifact, creature,
    or land on the battlefield, if it isn't a mana ability, this creature
    deals 2 damage to that player. — Harsh Mentor. First consumer of the
    new `EventType.ACTIVATED_ABILITY` (`GameEngine.activate_ability`, RULE
    602.2) — mana abilities never reach that event at all (RULE 605.1a:
    they never use the stack, resolving instead through `tap_for_mana`/
    `activate_hand_mana_ability`), so "isn't a mana ability" needs no
    filter of its own. "of an artifact, creature, or land" is simplified to
    "of a permanent" (artifact/creature/land cover the overwhelming
    majority of real activated abilities; a planeswalker/battle/
    enchantment-only activated ability triggering this too is a narrow,
    documented over-trigger rather than a missed one).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        )
    ]


register("Harsh Mentor", _harsh_mentor)
