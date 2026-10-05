from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _city_on_fire() -> list[AbilitySpec]:
    """Convoke
    If a source you control would deal damage to a permanent or player,
    it deals triple that damage instead.

    — Imodane deck batch. Convoke is a RULE 702 keyword, auto-bound; the
    replacement clause is word-for-word `Fiery Emancipation`'s own
    ``double_damage`` (``multiplier=3``, ``your_sources_only=True``).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"multiplier": 3, "your_sources_only": True})],
        ),
    ]


register("City on Fire", _city_on_fire)
