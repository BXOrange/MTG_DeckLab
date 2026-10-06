from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "if the exiled card's mana value is 4 or greater" — the printed threshold.
_BIG_MANA_VALUE = 4


def _summoners_sending() -> list[AbilitySpec]:
    """At the beginning of your end step, you may exile target creature card from a graveyard. If you do, create a 1/1 white Spirit creature token with flying. Put a +1/+1 counter on it if the exiled card's mana value is 4 or greater.

    — PLAY-ALL (Counter Blitz). One `exile_creature_card_make_spirit` effect (an optional creature card in any graveyard, ``any_graveyard_creature``)
    that exiles it and, if it did, makes the Spirit with the counter when the exiled card's mana value reaches ``min_mana_value_for_counter``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_creature_card_make_spirit", {"min_mana_value_for_counter": _BIG_MANA_VALUE})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Summoner's Sending", _summoners_sending)
