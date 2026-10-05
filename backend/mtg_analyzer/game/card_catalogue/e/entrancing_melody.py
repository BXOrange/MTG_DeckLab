from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# permanent (RULE 611.2 no-duration) gain-control one-shot (PAR-60)
# ===========================================================================
# `GainControlUntilEndOfTurnEffect` (Zealous Conscripts family) gained a
# ``duration`` axis: ``"permanent"`` + ``untap=False`` + ``haste=False`` is
# the Mind Control / Control Magic / Persuasion / Corrupted Conscience /
# Entrancing Melody family — a bare, non-reverting ``controller_id`` change.


def _entrancing_melody() -> list[AbilitySpec]:
    """Gain control of target creature with mana value X.

    Documented simplification: modeled as ``max_mana_value`` (mv <= X), the
    engine's only mana-value target cap — very slightly more permissive than
    the printed exact "mana value X", but the caster picks X to hit the
    creature they want anyway."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("gain_control_until_eot", {
                "target_kind": "creature", "max_mana_value": "x",
                "duration": "permanent", "untap": False, "haste": False,
            })],
        ),
    ]


register("Entrancing Melody", _entrancing_melody)
