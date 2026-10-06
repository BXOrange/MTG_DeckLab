from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: "Mutants, Ninjas, and/or Turtles" as one object filter.
_SUBJECTS = {"any_of": [{"subtype": "mutant"}, {"subtype": "ninja"}, {"subtype": "turtle"}]}


def _heroes_in_a_half_shell() -> list[AbilitySpec]:
    """Vigilance, menace, trample, haste
    Whenever one or more Mutants, Ninjas, and/or Turtles you control deal combat damage to a player, put a +1/+1 counter on each of those creatures and draw a card.

    — PLAY-ALL (Turtle Power!). The keywords are the card's. The trigger is the batch `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` head with an ``any_of`` subtype filter, over `add_counters` with the new
    ``trigger_contributors`` (each creature of the batch that matched) and a `draw`.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "trigger_contributors": _SUBJECTS}),
                EffectSpec("draw", {"count": 1}),
            ],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {"subject": "group", "controller": "you", "other": False, "filter": _SUBJECTS},
                "contributors": {"min": 1},
            },
        ),
    ]


register("Heroes in a Half Shell", _heroes_in_a_half_shell)
