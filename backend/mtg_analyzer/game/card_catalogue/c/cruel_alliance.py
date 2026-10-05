from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-85: RULE 702.194b Teamwork's *other* "instead" shape — a
# cast-time-conditional change to target legality or selection count, not a
# flat magnitude (PAR-68's `amount_if_teamwork` closed that half already:
# Helicarrier Strike, above). All three confirmed singleton via
# `parser_probe.py blocked`.
# ---------------------------------------------------------------------------


def _cruel_alliance() -> list[AbilitySpec]:
    """Teamwork 2 (As an additional cost to cast this spell, you may tap
    any number of creatures you control with total power 2 or more.)
    Exile target creature with mana value 3 or less. If this spell was
    cast using teamwork, instead exile target creature and you gain 3
    life.

    — MEC-85. The mana-value cap sits on the RULE 115 target itself, not
    the effect's magnitude — "instead exile target creature" drops the
    cap entirely rather than changing a number — so this needs `targeting.
    TargetSpec.unless_flag` (new), which clears `max_mana_value` for this
    one requirement when `teamwork_paid` reads true at target-offer time
    (RULE 601.2b: Teamwork's tap cost is chosen and paid before targets
    are chosen, RULE 601.2c). The life gain is an ordinary resolve-time
    `EffectSpec.condition={"teamwork_paid": True}` gate — PAR-56's own
    condition key, the same idiom Beast Mode's trailing counter clause
    above already uses.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {
                    "target_kind": "creature", "max_mana_value": 3,
                    "unless_flag": "teamwork_paid",
                }),
                EffectSpec(
                    "gain_life", {"amount": 3},
                    condition={"teamwork_paid": True},
                ),
            ],
        ),
    ]


register("Cruel Alliance", _cruel_alliance)
