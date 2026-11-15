from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cmdr_troi_outgoing_empath() -> list[AbilitySpec]:
    """Vigilance
    {T}: Target opponent whose turn it is may cast a spell from their hand without paying its mana cost. If they do, you copy that spell. You may choose new targets for the copy. If they don't, you draw a card."""
    return [AbilitySpec('activated', [EffectSpec('opponent_free_cast_copy_or_draw', {})],
                        cost={'taps_self': True})]


register('Cmdr. Troi, Outgoing Empath', _cmdr_troi_outgoing_empath)
