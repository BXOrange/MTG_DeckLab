from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "if you control a creature with power 7 or greater" — the printed threshold.
_BIG_POWER = 7


def _fight_rigging() -> list[AbilitySpec]:
    """Hideaway 5 (When this enchantment enters, look at the top five cards of your library, exile one face down, then put the rest on the bottom in a random order.)
    At the beginning of combat on your turn, put a +1/+1 counter on target creature you control. Then if you control a creature with power 7 or greater, you may play the exiled card without paying its mana cost.

    — PLAY-ALL (Counter Blitz). Hideaway is the keyword catalogue's. The combat trigger is `add_counters` on a target creature you
    control followed by Mosswort Bridge's `play_hideaway_card`, gated on a ``control_count`` condition (a creature with power 7 or
    greater) evaluated after the counter lands.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "hideaway", "n": 5}),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "target_kind": "creature_you_control"}),
                EffectSpec("play_hideaway_card", {"condition": {
                    "kind": "control_count", "selector": "creatures_you_control", "min_power": _BIG_POWER, "min": 1,
                }}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Fight Rigging", _fight_rigging)
