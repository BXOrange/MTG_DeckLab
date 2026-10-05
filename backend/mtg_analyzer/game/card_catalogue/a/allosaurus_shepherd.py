from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _allosaurus_shepherd() -> list[AbilitySpec]:
    """Allosaurus Shepherd (Creature — Elf Shaman, {G})

    "This spell can't be countered.
    Green spells you control can't be countered.
    {4}{G}{G}: Until end of turn, each Elf creature you control has base
    power and toughness 5/5 and becomes a Dinosaur in addition to its
    other creature types."

    The self-uncounterable static is already parser-claimable. The second
    static reuses `GrantCantBeCounteredEffect`'s new ``color`` param
    (MEC-40). The activated ability reuses the standing ``creatures_you_
    control_of_type_elf`` group selector (`continuous.group_selector_
    objects`, an already-general subtype-scoped anthem affects string) via
    `GrantUntilEffect` wrapping ``type_change`` — the same "until end of
    turn" resolve-time grant Crew's own "becomes an artifact creature"
    reuses (MEC-29).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_cant_be_countered", {"scope": "color_spells_you_control", "color": "G"})],
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "grant_until",
                    {
                        "static": {
                            "type": "type_change",
                            "params": {
                                "power": 5, "toughness": 5, "add_subtypes": ["Dinosaur"],
                                "affects": "creatures_you_control_of_type_elf",
                            },
                        },
                        "duration": "end_of_turn",
                        "target_kind": None,
                    },
                )
            ],
            cost={"text": "{4}{G}{G}"},
        ),
    ]


register("Allosaurus Shepherd", _allosaurus_shepherd)
