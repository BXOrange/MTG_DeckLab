from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _geralf_the_fleshwright() -> list[AbilitySpec]:
    """Whenever you cast a spell during your turn other than your first spell that turn, create a 2/2 blue and black Zombie Rogue creature token.
    Whenever a Zombie you control enters, put a +1/+1 counter on it for each other Zombie that entered the battlefield under your control this turn.

    — Commander Cube singleton batch. The first trigger is a SPELL_CAST trigger gated by `during_your_turn` and the
    `spells_cast_this_turn_at_least` intervening-if (RULE 603.4; the count includes the triggering spell). The second
    is a group ENTERS_BATTLEFIELD trigger over Zombies you control, whose body counts this turn's logged Zombie entries
    (`counters_per_other_entered_this_turn`, RULE 122.1 for the counters placed on the entering Zombie).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "power": 2, "toughness": 2, "colors": ["U", "B"],
                                         "subtypes": ["Zombie", "Rogue"], "keywords": [], "token_name": "Zombie Rogue"})],
            trigger={"event": "SPELL_CAST", "condition": {"subject": "you"},
                     "during_your_turn": True, "spells_cast_this_turn_at_least": 2},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("counters_per_other_entered_this_turn", {"subtype": "Zombie"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False, "filter": {"subtype": "zombie"},
            }},
        ),
    ]


register("Geralf, the Fleshwright", _geralf_the_fleshwright)
