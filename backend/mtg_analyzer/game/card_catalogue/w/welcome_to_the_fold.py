from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _welcome_to_the_fold() -> list[AbilitySpec]:
    """Madness {X}{U}{U}
    Gain control of target creature if its toughness is 2 or less. If this spell's madness cost was paid,
    instead gain control of that creature if its toughness is X or less.

    — PAR-139. The Madness keyword is bound from the card's own keyword list; the spell body is one `if_else`
    on the cast-time ``madness_cost_paid`` flag, each branch the same RULE 115 target (so one target is
    announced) gated on the *resolution-time* toughness of that target — ``{"kind": "toughness", "of":
    "target"}``, with ``"x"`` bound to the spell's announced X by `effect_conditions._evaluate`. Hand-authored
    because the parser has no "gain control of `<target>` if its `<characteristic>` is N or less" row; a
    conditional-on-the-target body is not a shape any other cached card shares.
    """

    def gain_control(limit: object) -> dict:
        return {
            "type": "gain_control_until_eot",
            "params": {"target_kind": "creature", "duration": "permanent", "haste": False, "untap": False},
            "condition": {"kind": "toughness", "of": "target", "max": limit},
        }

    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("if_else", {
                "condition": {"kind": "flag", "flag": "madness_cost_paid"},
                "then": [gain_control("x")],
                "else": [gain_control(2)],
            })],
        ),
    ]


register("Welcome to the Fold", _welcome_to_the_fold)
