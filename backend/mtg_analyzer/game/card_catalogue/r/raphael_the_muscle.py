from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _raphael_the_muscle() -> list[AbilitySpec]:
    """Double damage from your creatures with counters; make a Mutagen on entry."""
    return [
        AbilitySpec("replacement", [EffectSpec("double_damage", {"your_sources_only": True, "creature_only": True,
            "source_filter": {"has_counter": True}})]),
        AbilitySpec("triggered", [EffectSpec("create_token", {"token_name": "Mutagen", "count": 1})],
                    trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}}),
    ]


register('Raphael, the Muscle', _raphael_the_muscle)
