from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lwaxana_troi_charming_guest() -> list[AbilitySpec]:
    """You may choose not to untap Lwaxana Troi during your untap step.
    {2}, {T}: Choose another target creature you control. For as long as Lwaxana Troi remains tapped, if a triggered ability of that creature triggers, that ability triggers an additional time.
    """
    return [
        AbilitySpec('static',[EffectSpec('no_untap_optional',{})]),
        AbilitySpec('activated',[EffectSpec('grant_bound_trigger_doubler',{})],cost={'mana':'{2}','taps_self':True}),
    ]


register('Lwaxana Troi, Charming Guest',_lwaxana_troi_charming_guest)
