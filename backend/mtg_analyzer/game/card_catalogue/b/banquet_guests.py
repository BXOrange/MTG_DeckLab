from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _banquet_guests() -> list[AbilitySpec]:
    """Affinity for Foods
    Trample
    This creature enters with twice X +1/+1 counters on it.
    {2}, Sacrifice a Food: This creature gains indestructible until end of
    turn.

    (Affinity/Trample/the sacrifice-a-Food ability already parse on their
    own — only the X-scaled entry counters, which RULE 614.1's oracle-
    derived path can't express, needed hand-authoring.)
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"x_multiplier": 2})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Banquet Guests", _banquet_guests)
