from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _moonsilver_key() -> list[AbilitySpec]:
    """{1}, {T}, Sacrifice this artifact: Search your library for an
    artifact card with a mana ability or a basic land card, reveal it,
    put it into your hand, then shuffle.

    — MEC-12 (cEDH Kinnan). The new `card_query` ``"or"``/
    ``"has_mana_ability"`` keys — the first real compound ("X or Y")
    search criteria in the catalogue; every prior search criteria dict
    was a plain AND.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {
                    "or": [
                        {"type": "Artifact", "has_mana_ability": True},
                        {"basic": True},
                    ],
                },
                "destination": "hand",
            })],
            cost={"text": "{1}, {T}, Sacrifice ~"},
        ),
    ]


register("Moonsilver Key", _moonsilver_key)
