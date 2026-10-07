from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _display_of_power() -> list[AbilitySpec]:
    """This spell can't be copied.
    Copy any number of target instant and/or sorcery spells. You may
    choose new targets for the copies.

    — Imodane deck batch. "Any number of target spells" is the RULE
    601.2c "any number" idiom Fire Covenant's own ``count=10`` UI cap
    already established, applied to `CopySpellEffect`'s ``target_count``
    (new — every prior copy-spell card only ever named one target).
    Its static marker prohibits every spell-copy path, including forced
    copies, while target changes use the shared copy-target rounds.
    """
    return [
        AbilitySpec("static", [EffectSpec("cant_be_copied", {})]),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {
                "card_types": ["instant", "sorcery"], "target_count": 10, "optional": True,
            })],
        ),
    ]


register("Display of Power", _display_of_power)
