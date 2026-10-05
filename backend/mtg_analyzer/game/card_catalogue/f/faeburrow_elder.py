from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _faeburrow_elder() -> list[AbilitySpec]:
    """Vigilance
    This creature gets +1/+1 for each color among permanents you control.
    {T}: For each color among permanents you control, add one mana of
    that color.

    — MEC-43 round 2. Vigilance and the mana ability both already parse on
    their own (the latter via `mana_abilities_for`'s own oracle-text read,
    entirely independent of `bind_from_catalogue`/hand-authoring — see
    CLAUDE.md's RULE 605 note); only the P/T anthem needs hand-authoring,
    reusing Conqueror's Flail's own new ``colors_among_permanents_you_
    control`` selector with ``affects="self"``.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 1,
                "power_count": "colors_among_permanents_you_control",
                "toughness_count": "colors_among_permanents_you_control",
            })],
        )
    ]


register("Faeburrow Elder", _faeburrow_elder)
