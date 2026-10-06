from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _intruder_alarm() -> list[AbilitySpec]:
    """Creatures don't untap during their controllers' untap steps.
    Whenever a creature enters, untap all creatures.

    — PLAY-ALL (Shorikai Vehicles). The trigger is the parser's group head with its mass `tap` (``untap``) over every creature; the static is Meekstone's
    `no_untap` over ``all_creatures``.
    """
    return [
        AbilitySpec("static", [EffectSpec("no_untap", {"affects": "all_creatures"})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"selector": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature"}}, "untap": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "any", "other": False, "type": "creature",
            }},
        ),
    ]


register("Intruder Alarm", _intruder_alarm)
