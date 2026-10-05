from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _goreclaw_terror_of_qal_sisma() -> list[AbilitySpec]:
    """Creature spells you cast with power 4 or greater cost {2} less to cast.
    Whenever Goreclaw attacks, each creature you control with power 4 or greater gets +1/+1 and
    gains trample until end of turn.

    — Animated Army deck batch. The discount is `cost_reduction` with the new ``spell_min_power``
    filter (printed power of the spell being cast). The attack trigger is a group `pump` over the
    ``creatures you control with power ≥ 4`` selector, the Inspiring Call selector shape.
    """
    big = {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "min_power": 4}}
    return [
        AbilitySpec("static", [EffectSpec("cost_reduction", {
            "affects": "your_spells", "generic": 2, "spell_type": "creature", "spell_min_power": 4,
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"power": 1, "toughness": 1, "keywords": ["trample"], "selector": big})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Goreclaw, Terror of Qal Sisma", _goreclaw_terror_of_qal_sisma)
