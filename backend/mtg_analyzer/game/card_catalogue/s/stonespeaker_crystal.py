from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stonespeaker_crystal() -> list[AbilitySpec]:
    """{T}: Add {C}{C}.
    {2}, {T}, Sacrifice this artifact: Exile any number of target players' graveyards. Draw a card.
    """
    # The native mana-ability binder supplies the first printed ability.
    return [AbilitySpec('activated', [
        EffectSpec('exile_target_graveyard', {'any_number': True}),
        EffectSpec('draw', {'count': 1}),
    ], cost={'mana': '{2}', 'taps_self': True, 'sacrifice': 'self'},
        raw_text="{2}, {T}, Sacrifice this artifact: Exile any number of target players' graveyards. Draw a card.")]


register('Stonespeaker Crystal', _stonespeaker_crystal)
