from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_regatha() -> list[AbilitySpec]:
    """(As a Siege enters, choose an opponent to protect it. You and
    others can attack it. When it's defeated, exile it, then cast it
    transformed.)
    When this Siege enters, it deals 4 damage to another target battle
    or opponent and 1 damage to up to one target creature.

    — Imodane deck batch. Two independent targeting effects on one
    trigger, gathered one at a time (`_continue_trigger_multi_target`,
    RULE 603.1) rather than `GameEffect.extra_target_specs` — `damage`
    itself only ever reads a single flat targets list, so the second
    requirement needs its own effect, not a bolt-on second target on the
    first. The new `battle_or_opponent` target kind covers the first.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 4, "target_kind": "battle_or_opponent"}),
                EffectSpec("damage", {"amount": 1, "target_kind": "creature", "optional": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Invasion of Regatha", _invasion_of_regatha)
register("Invasion of Regatha // Disciples of the Inferno", _invasion_of_regatha)
