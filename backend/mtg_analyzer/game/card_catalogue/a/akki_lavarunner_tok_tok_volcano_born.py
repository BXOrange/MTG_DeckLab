from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _akki_lavarunner() -> list[AbilitySpec]:
    """Haste
    Whenever this creature deals damage to an opponent, flip it.
    """
    return [AbilitySpec('triggered', [EffectSpec('flip', {})], trigger={
        'event': EventType.DAMAGE, 'condition': {'subject': 'self'},
        'filter': {'is_player': True}, 'recipient_relation': 'opponent',
    })]


def _tok_tok() -> list[AbilitySpec]:
    """Protection from red
    If a red source would deal damage to a player, it deals that much damage plus 1 to that player instead.
    """
    return [AbilitySpec('replacement', [EffectSpec('additional_damage', {
        'amount': 1, 'color': 'R', 'players_only': True,
    })])]


register('Akki Lavarunner', _akki_lavarunner)
register('Tok-Tok, Volcano Born', _tok_tok)
