from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _skyway_robber() -> list[AbilitySpec]:
    """Flying
    Escape—{3}{U}, Exile five other cards from your graveyard. (You may cast this card from your graveyard for its escape cost.)
    This creature escapes with "Whenever this creature deals combat damage to a player, you may cast an artifact, instant, or sorcery spell from among cards exiled with this creature without paying its mana cost."
    """
    return [AbilitySpec('static', [EffectSpec('grant_triggered_ability', {
        'affects': 'self', 'active_if': {'kind': 'flag', 'flag': 'cast_via_escape'},
        'trigger_event': EventType.DAMAGE, 'filter': {'combat': True, 'is_player': True},
        'grant_effects': [{'type': 'skyway_robber_cast', 'params': {}}],
    })])]


register('Skyway Robber', _skyway_robber)
