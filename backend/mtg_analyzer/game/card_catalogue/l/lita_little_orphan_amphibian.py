from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lita_little_orphan_amphibian() -> list[AbilitySpec]:
    """Alliance modes are chosen when stacking and each is available once per turn."""
    return [AbilitySpec("triggered", [],
        trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "group", "controller": "you", "other": True,
            "filter": {"card_type": "creature"}}},
        modes={"choose": 1, "exhaust_per_turn": True, "options": [
            [EffectSpec("add_counters", {"count": 1})],
            [EffectSpec("create_token", {"token_name": "Food", "count": 1})],
            [EffectSpec("scry", {"count": 1})],
        ], "descriptions": ["+1/+1-Marke auf Lita", "Food erzeugen", "Scry 1"]})]


register('Lita, Little Orphan Amphibian', _lita_little_orphan_amphibian)
