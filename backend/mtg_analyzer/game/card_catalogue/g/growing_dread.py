from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _growing_dread() -> list[AbilitySpec]:
    """Flash
    When this enchantment enters, manifest dread. (Look at the top two cards of your library. Put one onto the battlefield face down as a 2/2 creature and the other into your graveyard. Turn it face up any time for its mana cost if it's a creature card.)
    Whenever you turn a permanent face up, put a +1/+1 counter on it.

    — PLAY-ALL (Jump Scare!). Flash is a keyword and the manifest-dread trigger is the parser's. The counter trigger is a
    group `TURNED_FACE_UP` trigger over your permanents whose body reads the firing permanent
    (``trigger_subject_key: __group_subject__``, the "put a +1/+1 counter on it" shape).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("manifest_dread", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "trigger_subject_key": "__group_subject__"})],
            trigger={"event": EventType.TURNED_FACE_UP, "condition": {"subject": "group", "controller": "you", "other": False}},
        ),
    ]


register("Growing Dread", _growing_dread)
