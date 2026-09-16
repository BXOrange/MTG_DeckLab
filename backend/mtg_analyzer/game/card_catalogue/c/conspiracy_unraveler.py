from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _conspiracy_unraveler() -> list[AbilitySpec]:
    """Flying
    You may collect evidence 10 rather than pay the mana cost for spells you
    cast.

    — PAR-30 (Collect Evidence / Forage / Blight residue). Flying parses;
    the RULE 118.9 board-wide alternative-cost grant is the
    `granted_alt_cast_cost` static (`continuous.granted_alt_cast_cost_for`,
    consulted by the engine's ``alt_cost=True`` cast path — `can_cast` /
    `cast_spell` / legal-actions `_offer_cast`). Controller-scoped ("spells
    **you** cast"); the alternative cost is `collect evidence 10`, paid via
    the same `RulesEngine.collect_evidence` primitive PAR-29 built.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec(
            "static",
            [EffectSpec("granted_alt_cast_cost", {"collect_evidence": 10})],
        ),
    ]


register("Conspiracy Unraveler", _conspiracy_unraveler)
