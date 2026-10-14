from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _brad_boimler_eager_ensign() -> list[AbilitySpec]:
    """Lifelink
    Whenever Brad Boimler becomes tapped, until end of turn, if one or more counters would be put on a permanent you
    control, that many plus one of each of those kinds of counters are put on that permanent instead.

    PAR-109. Lifelink is the printed keyword. The trigger (`EventType.TAPPED`, RULE 701.21b) installs the turn-scoped
    sibling of the standing `double_counters` ``plus`` replacement (RULE 614/616, `plus_counters_this_turn`): it is a
    replacement effect created by a resolving ability, so it applies from then until the turn ends, whoever's
    permanent Brad Boimler is.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("plus_counters_this_turn", {"plus": 1})],
            trigger={"event": EventType.TAPPED, "condition": {"subject": "self"}},
        ),
    ]


register("Brad Boimler, Eager Ensign", _brad_boimler_eager_ensign)
