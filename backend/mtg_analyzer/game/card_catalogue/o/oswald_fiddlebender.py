from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _oswald_fiddlebender() -> list[AbilitySpec]:
    """Magical Tinkering — {W}, {T}, Sacrifice an artifact: Search your
    library for an artifact card with mana value equal to 1 plus the
    sacrificed artifact's mana value, put it onto the battlefield, then
    shuffle. Activate only as a sorcery.

    — MEC-43, Birthing Pod's own artifact-scoped mirror, closing the same
    activation-cost sacrifice-stamp cluster's second card. "Magical
    Tinkering" is a bare ability word (RULE 207.2c) — flavour only, no
    rules meaning, so it's dropped rather than modeled.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact"},
                "destination": "battlefield",
                "mana_value_from": {"source": "sacrificed_cost", "plus": 1, "cmp": "eq"},
            })],
            cost={"text": "{W}, {T}, Sacrifice an artifact", "sorcery_speed_only": True},
        ),
    ]


register("Oswald Fiddlebender", _oswald_fiddlebender)
