from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _battletide_alchemist() -> list[AbilitySpec]:
    """If a source would deal damage to a player, you may prevent X of that
    damage, where X is the number of Clerics you control.

    — **Documented simplification**: modeled as an unconditional (always
    applied) prevention rather than a real "you may" — no replacement-level
    optional-choice primitive exists in this engine, and building one is
    not justified for this single card (see `BACKLOG.md`'s `MEC-30`).
    ``amount_count_selector="creatures_you_control_of_type_cleric"`` is the
    same generic count-selector key Shield of the Avatar already uses for
    its own unscoped "number of creatures you control" form.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "any_player",
                "amount_count_selector": "creatures_you_control_of_type_cleric",
            })],
        ),
    ]


register("Battletide Alchemist", _battletide_alchemist)
