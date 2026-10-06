from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _endless_detour() -> list[AbilitySpec]:
    """The owner of target spell, nonland permanent, or card in a graveyard puts it on their choice of the top or bottom of their library.

    — PLAY-ALL (Counter Blitz). Plan for All Outcomes' `owner_puts_on_top_or_bottom` (a RULE 401.4 `library_position` choice opened for the
    target's *owner*) over the new three-way target kind ``spell_nonland_permanent_or_graveyard_card``; a spell target leaves the stack through
    `move_spell_off_stack` (a copy simply ceases to exist), a graveyard card moves through `return_to_library`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("owner_puts_on_top_or_bottom", {
                "target_kind": "spell_nonland_permanent_or_graveyard_card", "optional": False,
            })],
        ),
    ]


register("Endless Detour", _endless_detour)
