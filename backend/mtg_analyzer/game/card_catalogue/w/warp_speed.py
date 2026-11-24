
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _warp_speed() -> list[AbilitySpec]:
    'Lands you control enter untapped.\nWhen this enchantment enters, search your library for a basic land card or Planet card, reveal it, put it into your hand, then shuffle.\nStrange new worlds — {7}{U}{U}, Sacrifice this enchantment: Draw two cards. This ability costs {X} less to activate, where X is the number of differently named lands you control.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('search', {"criteria": {'or': [{'basic': True}, {'type': 'planet'}]}, "destination": 'hand'})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='when ~ enters, search your library for a basic land card or planet card, reveal it, put it into your hand, then shuffle.',
        ),
        AbilitySpec(
            'activated',
            [EffectSpec('draw', {"count": 2})],
            cost={"text": '{7}{u}{u}, sacrifice ~', "dynamic_reduction": {'count_selector': {'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'land'}, 'distinct': 'name'}, 'generic_per': 1}},
            raw_text='{7}{u}{u}, sacrifice ~: draw 2 cards. this ability costs {x} less to activate, where x is the number of differently named lands you control.',
        ),
        # RULE 614.1: Horizon Explorer's static; it replaces a land's own "enters tapped" for the controller's lands.
        AbilitySpec("static", [EffectSpec("lands_enter_untapped", {})], raw_text="lands you control enter untapped."),
    ]


register('Warp Speed', _warp_speed)
