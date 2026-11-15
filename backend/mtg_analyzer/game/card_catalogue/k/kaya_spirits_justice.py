"""Kaya's exile pool fixes a token target before choosing an exiled creature card."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kaya_spirits_justice():
    'Whenever one or more creatures you control and/or creature cards in your graveyard are put into exile, you may choose a creature card from among them. Until end of turn, target token you control becomes a copy of it, except it has flying.\n+2: Surveil 2, then exile a card from a graveyard.\n+1: Create a 1/1 white and black Spirit creature token with flying.\n−2: Exile target creature you control. For each other player, exile up to one target creature that player controls.'
    return [AbilitySpec('triggered', [EffectSpec('exile_creature_token_copy', {})],
        trigger={'event': EventType.EVENT_BATCH, 'exile_creature_pool': True}),
        AbilitySpec('activated', [EffectSpec('surveil', {'count': 2}),
            EffectSpec('exile_chosen_graveyard_card', {})], cost={'loyalty': 2}),
        AbilitySpec('activated', [EffectSpec('create_token', {'count': 1, 'power': 1, 'toughness': 1,
            'colors': ['W', 'B'], 'subtypes': ['Spirit'], 'keywords': ['flying'], 'token_name': 'Spirit'})],
            cost={'loyalty': 1}),
        AbilitySpec('activated', [EffectSpec('exile_own_and_other_creatures', {})], cost={'loyalty': -2})]


register("Kaya, Spirits' Justice", _kaya_spirits_justice)
