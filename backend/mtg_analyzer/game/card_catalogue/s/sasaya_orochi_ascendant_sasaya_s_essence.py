from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sasaya() -> list[AbilitySpec]:
    """Reveal your hand: If you have seven or more land cards in your hand, flip Sasaya."""
    return [AbilitySpec('activated', [EffectSpec('flip', {}, condition={
        'kind': 'control_count', 'selector': {'zone': 'hand', 'of': 'you', 'filter': {'card_type': 'land'}},
        'min': 7,
    })], cost={'reveal_hand': True})]


def _sasayas_essence() -> list[AbilitySpec]:
    """Whenever a land you control is tapped for mana, add an additional one mana of any type that land produced for each other land you control with the same name as it."""
    return [AbilitySpec('triggered', [EffectSpec('sasaya_mana', {})], trigger={
        'event': EventType.TAPPED_FOR_MANA,
        'condition': {'subject': 'you'},
        'spell_filter': {'card_type': 'land'},
        'mana_ability': True,
    })]


register('Sasaya, Orochi Ascendant', _sasaya)
register("Sasaya's Essence", _sasayas_essence)
