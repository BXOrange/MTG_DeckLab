from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _imposter_mech() -> list[AbilitySpec]:
    """You may have this Vehicle enter as a copy of a creature an opponent
    controls, except it's a Vehicle artifact with crew 3 and it loses all
    other card types.
    Crew 3

    — MEC-12 (cEDH staples 2). The printed "Crew 3" (own copy, before any
    "enters as a copy" choice) is already parser-claimed for free; the
    "except" clause needs `only_types` (RULE 707.2's copiable card types
    replaced wholesale, not appended — `Card.as_copy` moves the copied
    creature's power/toughness to the vehicle-style slot since a
    non-creature can't carry plain `power`/`toughness`) plus `add_subtypes`
    for the Vehicle subtype and `add_keywords` to re-grant "Crew 3" itself,
    since RULE 707.2 would otherwise replace it with the copied creature's
    text (which has no Crew line of its own).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature_you_dont_control",
                "only_types": ["Artifact"], "add_subtypes": ["Vehicle"],
                "add_keywords": ["Crew 3"],
            })],
        ),
    ]


register("Imposter Mech", _imposter_mech)
