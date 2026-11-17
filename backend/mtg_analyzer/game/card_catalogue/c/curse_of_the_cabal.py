from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    "Target player sacrifices half the permanents they control of their choice, rounded down.\nSuspend 2—{2}{B}{B} (Rather than cast this card from your hand, you may pay {2}{B}{B} and exile it with two time counters on it. At the beginning of your upkeep, remove a time counter. When the last is removed, you may cast it without paying its mana cost.)\nAt the beginning of each player's upkeep, if this card is suspended, that player may sacrifice a permanent of their choice. If the player does, put two time counters on this card."
    return [
        AbilitySpec(
            'keyword',
            [],
            keyword={"name": 'suspend', "n": 2, "cost": '{2}{B}{B}'},
            raw_text='Suspend 2—{2}{B}{B} (Rather than cast this card from your hand, you may pay {2}{B}{B} and exile it with two time counters on it. At the beginning of your upkeep, remove a time counter. When the last is removed, you may cast it without paying its mana cost.)',
        ),
        AbilitySpec(
            'spell_effect',
            [EffectSpec('sacrifice', {"what": 'permanent', "count": 1, "target_kind": 'player', "pool_fraction": {'divisor': 2, 'round_up': False}})],
            raw_text='target player sacrifices half the permanents they control of their choice, rounded down.',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('suspended_sacrifice_offer', {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'upkeep'}, "functions_while_suspended": True},
            raw_text='',
        ),
    ]


register('Curse of the Cabal', _card)
