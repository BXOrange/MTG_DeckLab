from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _autumns_veil() -> list[AbilitySpec]:
    """Spells you control can't be countered by blue or black spells this
    turn, and creatures you control can't be the targets of blue or black
    spells this turn.

    — MEC-41. New `grant_cant_be_target_of_spell_color` for the second
    clause — RULE 115's own targeting restriction, deliberately narrower
    than hexproof (which also blocks *abilities*, and which this engine
    has no colour-qualified form of yet — Veil of Summer's own entry
    documents that gap) and than full protection (which also blocks
    damage/blocking/enchanting); see the effect's own docstring.
    **Documented simplification**: the first clause is modeled as
    unconditional "can't be countered this turn" (Veil of Summer's own
    `mark_your_spells_on_stack_cant_be_countered`/`arm_spell_watcher
    (repeat=True)` shape) rather than qualified by the countering spell's
    own colour — `RulesEngine._is_cant_be_countered`'s RULE 118 check has
    no notion of *what* is doing the countering at all, only whether the
    target carries the marker, and this is a strict *widening* (protects
    against every counterspell, not just blue/black ones) rather than a
    wrongly-narrower one; non-blue/black counterspells are rare enough
    that building the qualified form is disproportionate to this one card.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("mark_your_spells_on_stack_cant_be_countered", {}),
                EffectSpec("arm_spell_watcher", {
                    "then_specs": [{"type": "mark_cant_be_countered", "params": {}}],
                    "repeat": True,
                }),
                EffectSpec("grant_cant_be_target_of_spell_color", {
                    "colors": ["U", "B"], "selector": "creatures_you_control",
                }),
            ],
        ),
    ]


register("Autumn's Veil", _autumns_veil)
