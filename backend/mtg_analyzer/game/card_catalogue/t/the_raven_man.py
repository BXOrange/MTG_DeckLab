
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_raven_man() -> list[AbilitySpec]:
    'At the beginning of each end step, if a player discarded a card this turn, create a 1/1 black Bird creature token with flying and "This token can\'t block."\n{3}{B}, {T}: Each opponent discards a card. Activate only as a sorcery.'
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('discard', {"count": 1, "scope": 'each_opponent'}), EffectSpec('sorcery_speed_marker', {})],
            cost={"text": '{3}{b}, {t}'},
            raw_text='{3}{b}, {t}: each opponent discards a card. activate only as a sorcery.',
        ),
        AbilitySpec("triggered", [EffectSpec("create_token", {
            "count": 1, "power": 1, "toughness": 1, "colors": ["B"], "subtypes": ["Bird"],
            "keywords": ["flying", "cant_block"], "token_name": "Bird",
        })], trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
            "active_if": {"kind": "event_this_turn", "min": 1, "trigger": {
                "event": EventType.DISCARD_CARD, "condition": {"subject": "global"},
            }}}),
    ]


register('The Raven Man', _the_raven_man)
