from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _master_chef() -> list[AbilitySpec]:
    """Commander creatures you own have "This creature enters with an
    additional +1/+1 counter on it" and "Other creatures you control enter
    with an additional +1/+1 counter on them."

    — PAR-32 / MEC-56. A twin-quoted grant body (`"A" and "B"`), which
    `_quoted_ability_grant_effects_list`'s single-inner-body recursion
    can't split; hand-authored rather than widening that grammar for a
    shape only this card uses. Both clauses reduce to the same new
    ``extra_etb_counter`` static (RULE 614.1 entry-counter replacement,
    `continuous.extra_etb_counters_for`) granted onto every commander
    creature the controller owns (`affects="commander_creatures_you_own"`,
    the existing PAR-32 selector): ``self_only`` for "this creature enters
    with…", unset for "other creatures you control enter with…" — read off
    each grantee's own ``source`` at grant time, so this still works
    correctly with two or more commander creatures on the same board.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("grant_static_ability", {
                    "affects": "commander_creatures_you_own",
                    "static_specs": [
                        {"type": "extra_etb_counter",
                         "params": {"kind": "+1/+1", "count": 1, "self_only": True}},
                    ],
                }),
                EffectSpec("grant_static_ability", {
                    "affects": "commander_creatures_you_own",
                    "static_specs": [
                        {"type": "extra_etb_counter",
                         "params": {"kind": "+1/+1", "count": 1, "self_only": False}},
                    ],
                }),
            ],
        ),
    ]


register("Master Chef", _master_chef)
