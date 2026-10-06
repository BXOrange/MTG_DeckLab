from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _teferis_reproach() -> list[AbilitySpec]:
    """Choose target opponent. Until that player's next turn, they gain protection from everything and their life total can't
    change. All nonland permanents they control phase out. (While they're phased out, they're treated as though they don't
    exist. They phase in before that player untaps during their next untap step.)
    Exile Teferi's Reproach.

    — PLAY-ALL (Multiverse Reforged). Teferi's Protection's `phase_out_all_you_control` aimed at a target opponent
    (``target_kind="opponent"``, ``nonland_only``): the player shield and the mass phase-out share the one "until that player's
    next turn" duration (the RULE 702.26a untap sweep phases the permanents back in; `GameEngine.begin_turn` sweeps the
    shield). The second paragraph is the shipped `exile` self mode.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("phase_out_all_you_control", {"target_kind": "opponent", "nonland_only": True}),
                EffectSpec("exile", {"target_kind": None}),
            ],
        ),
    ]


register("Teferi's Reproach", _teferis_reproach)
