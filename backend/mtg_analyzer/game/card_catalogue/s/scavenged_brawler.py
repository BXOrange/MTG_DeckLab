
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scavenged_brawler() -> list[AbilitySpec]:
    'Flying, vigilance, trample, lifelink\n{5}, Exile this card from your graveyard: Choose target creature. Put four +1/+1 counters, a flying counter, a vigilance counter, a trample counter, and a lifelink counter on that creature. Activate only as a sorcery.'
    return [
        AbilitySpec("activated", [
            EffectSpec("add_counters", {"amount": 4, "target_kind": "creature"}),
            *[EffectSpec("add_counters", {"amount": 1, "kind": kind, "previous_subject": True})
              for kind in ("flying", "vigilance", "trample", "lifelink")],
            EffectSpec("sorcery_speed_marker", {}),
        ], cost={"text": "{5}, exile this card from your graveyard"}),
    ]


register('Scavenged Brawler', _scavenged_brawler)
