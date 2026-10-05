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
    **Documented simplification**: "This spell can't be copied" (RULE
    707.12) isn't modeled — no spell-copy-immunity primitive exists yet,
    and nothing in either deck tries to copy a spell that's still on the
    stack as a copy target — so it's harmless in practice; "you may
    choose new targets for the copies" is the same already-documented
    MVP `CopySpellEffect` simplification every other copy-spell card in
    this catalogue shares (keeps the original's targets).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {
                "card_types": ["instant", "sorcery"], "target_count": 10, "optional": True,
            })],
        ),
    ]


register("Display of Power", _display_of_power)
