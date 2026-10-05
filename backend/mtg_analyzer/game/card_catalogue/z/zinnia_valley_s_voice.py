from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _zinnia_valley_s_voice() -> list[AbilitySpec]:
    """Flying
    Zinnia gets +X/+0, where X is the number of other creatures you control with base power 1.
    Creature spells you cast gain offspring {2} as you cast them. (You may pay an additional {2} as you cast
    a creature spell. If you do, when that creature enters, create a 1/1 token copy of it.)

    — Family Matters deck batch. The pump is a self `anthem` whose per-unit count is a structured selector
    (PAR-120) over the ``base_power`` filter key ("base power" is the printed/copied value, not the derived
    one) with ``not_reference`` for "other". The offspring grant is the new `grant_offspring` static
    (`continuous.granted_offspring_cost_for`): `GameEngine._kicker_cost` falls back to it, so the usual
    kicker announcement offers {2}, and the cast binds the Offspring ETB trigger onto the spell.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 0,
                "power_count": {
                    "zone": "battlefield", "of": "you",
                    "filter": {"card_type": "creature", "base_power": 1, "not_reference": True},
                },
                "toughness_count": {
                    "zone": "battlefield", "of": "you",
                    "filter": {"card_type": "creature", "base_power": 1, "not_reference": True},
                },
            })],
        ),
        AbilitySpec("static", [EffectSpec("grant_offspring", {"cost": "{2}"})]),
    ]


register("Zinnia, Valley's Voice", _zinnia_valley_s_voice)
