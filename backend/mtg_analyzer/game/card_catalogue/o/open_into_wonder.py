from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

# RULE 107.3c / 601.2c: X is announced on cast and the number of targets is X, so the target requirement
# is a `count_selector="source_x_paid"` range (0..X, "optional" lets X = 0 cast with no target) with a
# printed-count ceiling that only bounds the offer rounds (the Icy Blast / Immoral Bargain idiom).
OPEN_INTO_WONDER_MAX_TARGETS = 10


def _open_into_wonder() -> list[AbilitySpec]:
    'X target creatures can\'t be blocked this turn. Until end of turn, those creatures gain "Whenever this creature deals combat damage to a player, draw a card."'
    # RULE 611.2c: the continuous grant affects only the creatures chosen as the spell resolves
    # ("those creatures" = `previous_subject`, the clause-1 targets), not creatures that arrive later.
    # RULE 603.1: the granted trigger is a real triggered ability whose source is each affected creature
    # (the Subterfuge idiom), a combat-damage-to-a-player DAMAGE event (RULE 120.3 / 510.2).
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("unblockable", {
                    "target_kind": "creature", "count": OPEN_INTO_WONDER_MAX_TARGETS,
                    "count_selector": "source_x_paid", "optional": True,
                }),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn",
                    "previous_subject": True,
                    "static": {
                        "type": "grant_triggered_ability",
                        "params": {
                            "trigger_event": EventType.DAMAGE,
                            "filter": {"combat": True, "is_player": True},
                            "grant_effects": [{"type": "draw", "params": {"count": 1}}],
                        },
                    },
                }),
            ],
        ),
    ]


register('Open into Wonder', _open_into_wonder)
