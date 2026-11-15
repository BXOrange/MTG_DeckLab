from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register, register_token


def _human() -> list[AbilitySpec]:
    return [AbilitySpec('static', [EffectSpec('phase_in_prohibition', {})],
                        raw_text="Permanents can't phase in.")]


def _the_city_on_the_edge_of_forever() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
    I — All artifacts and creatures phase out. Create a 0/1 white Human creature token with "Permanents can't phase in." (Treat phased-out permanents and anything attached to them as though they don't exist.)
    II — You draw two cards and each player loses 2 life.
    III — Sacrifice a creature token. If you do, you gain 5 life.
    """
    return [
        AbilitySpec('triggered', [
            EffectSpec('phase_out', {'selector': 'artifacts_and_creatures'}),
            EffectSpec('create_token', {'count': 1, 'power': 0, 'toughness': 1,
                'colors': ['W'], 'subtypes': ['Human'], 'oracle_text': "Permanents can't phase in."}),
        ], trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [1]}),
        AbilitySpec('triggered', [EffectSpec('draw', {'count': 2}),
            EffectSpec('lose_life', {'amount': 2, 'selector': 'each_player'})],
            trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [2]}),
        AbilitySpec('triggered', [EffectSpec('sacrifice_chosen_then', {
            'what': 'creature_token', 'count': 1, 'optional': False,
            'effects': [{'type': 'gain_life', 'params': {'amount': 5}}],
        })], trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [3]}),
    ]


register('The City on the Edge of Forever', _the_city_on_the_edge_of_forever)
register_token('Human', "Permanents can't phase in.", _human)
