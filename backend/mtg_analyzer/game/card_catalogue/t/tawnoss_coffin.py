from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tawnoss_coffin():
    """You may choose not to untap this artifact during your untap step.
    {3}, {T}: Exile target creature and all Auras attached to it. Note the number and kind of counters that were on that creature. When this artifact leaves the battlefield or becomes untapped, return that exiled card to the battlefield under its owner's control tapped with the noted number and kind of counters on it. If you do, return the other exiled cards to the battlefield under their owner's control attached to that permanent.
    """
    return [
        AbilitySpec('static', [EffectSpec('no_untap_optional', {})]),
        AbilitySpec('activated', [EffectSpec('exile_attached_group', {
            'release': 'source_release', 'remember_counters': True,
        })], cost={'text': '{3}, {T}'}),
    ]


register("Tawnos's Coffin", _tawnoss_coffin)
