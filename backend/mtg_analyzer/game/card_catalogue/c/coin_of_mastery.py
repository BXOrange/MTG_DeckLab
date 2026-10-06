from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _coin_of_mastery() -> list[AbilitySpec]:
    """Each creature you control enters with an additional +1/+1 counter on it for each mana from an artifact source spent to cast it.
    {T}: Create a Treasure token. (It's an artifact with "{T}, Sacrifice this token: Add one mana of any color.")

    — PLAY-ALL (Turtle Power!). The tap ability is the parser's claim. The counters are the ``extra_etb_counter`` static with the new ``count_per_artifact_mana`` (`continuous.extra_etb_counters_for`): the
    cast creature's ``mana_spent_to_cast_artifact`` (Treasures and other artifacts; `mana_source_kind_for` now tags a non-Treasure artifact source ``artifact``).
    """
    return [
        AbilitySpec("static", [EffectSpec("extra_etb_counter", {"kind": "+1/+1", "count_per_artifact_mana": True, "other": False, "filter": {"card_type": "creature"}})]),
        AbilitySpec("activated", [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})], cost={"text": "{t}"}),
    ]


register("Coin of Mastery", _coin_of_mastery)
