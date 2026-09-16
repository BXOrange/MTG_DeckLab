from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _neoform() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Search your library for a creature card with mana value equal to 1 plus
    the sacrificed creature's mana value, put that card onto the battlefield
    with an additional +1/+1 counter on it, then shuffle.

    — Neoform. Eldritch Evolution's sibling (see that entry for the
    ``mana_value_from`` channel), with two differences: the bound is
    *exact* rather than "or less" (``"cmp": "eq"``, emitted as a two-sided
    min/max since `models.cards.card_query` has no single "exactly N" key), and
    the found card arrives with a counter already on it
    (``extra_counters``, applied by `RulesEngine._finish_search` the moment
    it reaches the battlefield — RULE 614.1c-adjacent, but applied here
    rather than as an entry replacement because the counter comes from the
    *searching effect*, not the card's own printed text).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"},
                "destination": "battlefield",
                "mana_value_from": {"source": "sacrificed_cost", "plus": 1, "cmp": "eq"},
                "extra_counters": {"kind": "+1/+1", "count": 1},
            })],
            additional_cost={"sacrifice": "creature"},
        ),
    ]


register("Neoform", _neoform)
