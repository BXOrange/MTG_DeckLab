from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "chooses six lands they control" / "deals 6 damage" — the printed number.
_KEPT_LANDS = 6


def _planetary_annihilation() -> list[AbilitySpec]:
    """Each player chooses six lands they control, then sacrifices the rest.
    Planetary Annihilation deals 6 damage to each creature.

    — PLAY-ALL Step 2 (World Shaper). "Choose six, sacrifice the rest" is the
    mass edict `sacrifice` (``selector: each_player``, ``what: land``) with the
    generalized count ``all_but_6`` (`RulesEngine.sacrifice`: keep N, sacrifice
    the rest — the interactive chooser decides *which* go, which is the same
    choice seen from the other side), then a `damage` to each creature.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("sacrifice", {"selector": "each_player", "what": "land", "count": f"all_but_{_KEPT_LANDS}"}),
                EffectSpec("damage", {"amount": 6, "selector": "each_creature"}),
            ],
        ),
    ]


register("Planetary Annihilation", _planetary_annihilation)
