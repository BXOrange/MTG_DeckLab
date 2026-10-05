from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _giggling_skitterspike() -> list[AbilitySpec]:
    """Indestructible
    Whenever this creature attacks, blocks, or becomes the target of a spell,
    it deals damage equal to its power to each opponent.
    {5}: Monstrosity 5. (If this creature isn't monstrous, put five +1/+1
    counters on it and it becomes monstrous.)

    — PLAY-ALL Step 2 (Wick Snail Boom). Indestructible is a printed keyword.
    Monstrosity is the parser's own claim. The three-way trigger head isn't
    claimed as one clause, but each member is on its own
    (`subject_damages_each_opponent_equal_to_power` on ATTACKS, BLOCKS and
    BECOMES_TARGET filtered to ``item_kind: spell``, probed one by one), so it
    is three triggered abilities — each firing separately, which is the same
    outcome as the printed "attacks, blocks, or becomes the target" since
    only one of those events happens at a time.
    """
    damage = "subject_damages_each_opponent_equal_to_power"
    return [
        AbilitySpec(
            "triggered", [EffectSpec(damage, {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered", [EffectSpec(damage, {})],
            trigger={"event": EventType.BLOCKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered", [EffectSpec(damage, {})],
            trigger={
                "event": EventType.BECOMES_TARGET, "condition": {"subject": "self"},
                "filter": {"item_kind": "spell"},
            },
        ),
        AbilitySpec("activated", [EffectSpec("monstrosity", {"amount": 5})], cost={"text": "{5}"}),
    ]


register("Giggling Skitterspike", _giggling_skitterspike)
