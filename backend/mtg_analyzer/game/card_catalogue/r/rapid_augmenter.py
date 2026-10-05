from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rapid_augmenter() -> list[AbilitySpec]:
    """Haste
    Whenever another creature you control with base power 1 enters, it gains haste until end of turn.
    Whenever another creature you control enters, if it wasn't cast, put a +1/+1 counter on this creature and
    this creature can't be blocked this turn.

    — Family Matters deck batch. Haste is a keyword and the second trigger the parser's own claim. The
    first is a group `ENTERS_BATTLEFIELD` trigger filtered to ``base_power: 1`` whose body grants haste to the
    entering creature (`grant_keyword_to_trigger_subject`, the Tyvar Kell emblem's effect).
    """
    entering = {"subject": "group", "controller": "you", "other": True, "type": "creature"}
    return [
        AbilitySpec(
            "triggered", [EffectSpec("grant_keyword_to_trigger_subject", {"keyword": "haste"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {**entering, "filter": {"base_power": 1}}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"}, condition={
                "kind": "not", "condition": {"kind": "flag", "flag": "was_cast", "of": "trigger_subject"}}),
             EffectSpec("unblockable", {"target_kind": None})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": dict(entering)},
        ),
    ]


register("Rapid Augmenter", _rapid_augmenter)
