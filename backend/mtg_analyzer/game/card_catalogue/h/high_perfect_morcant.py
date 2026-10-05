from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _high_perfect_morcant() -> list[AbilitySpec]:
    """Whenever High Perfect Morcant or another Elf you control enters,
    each opponent blights 1. (They each put a -1/-1 counter on a creature
    they control.)
    Tap three untapped Elves you control: Proliferate. Activate only as a
    sorcery.

    — Eliferate deck batch. The activated ability already parses on its
    own — reproduced here verbatim. The ETB trigger is the new
    `each_opponent_counter_own_creature` primitive — see its docstring
    for the documented auto-pick simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("each_opponent_counter_own_creature", {"amount": 1, "kind": "-1/-1"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self_or_group", "subtypes": ["elf"], "controller": "you", "other": True},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("proliferate", {}), EffectSpec("sorcery_speed_marker", {})],
            cost={"text": "Tap three untapped Elves you control"},
        ),
    ]


register("High Perfect Morcant", _high_perfect_morcant)
