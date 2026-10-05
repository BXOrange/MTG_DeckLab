from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _charm_peddler() -> list[AbilitySpec]:
    """{W}, {T}, Discard a card: The next time a source of your choice would
    deal damage to target creature this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "creature", "amount": "all",
            })],
            cost={"text": "{W}, {T}, Discard a card"},
        ),
    ]


register("Charm Peddler", _charm_peddler)
