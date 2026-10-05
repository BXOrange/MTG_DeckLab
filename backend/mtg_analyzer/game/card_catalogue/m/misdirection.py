from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# --- cEDH lists batch: RULE 115.4 "change the target" -----------------------
#
# New primitive: `ChangeTargetEffect`/`RulesEngine.change_target` (RULE
# 115.4/601.2c) — a genuine retarget of an *existing* stack item, not the
# already-shipped "choose new targets for a freshly-made copy" (RULE
# 707.10c). Scoped to a spell with exactly one existing target (see
# `ChangeTargetEffect`'s own docstring); both real cards below only ever
# retarget a single-target spell.


def _misdirection() -> list[AbilitySpec]:
    """You may exile a blue card from your hand rather than pay this
    spell's mana cost.
    Change the target of target spell with a single target.

    **Documented simplification**: the free-cast alternative cost (RULE
    118.9, same drop precedent as the Force of Will cycle) is dropped.
    Fully castable at its printed {3}{U}{U}; the retarget itself is the
    new `change_target` primitive above, mandatory (no "may") per the
    printed text.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("change_target", {"single_target": True})],
        )
    ]


register("Misdirection", _misdirection)
