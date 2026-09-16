from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ponder() -> list[AbilitySpec]:
    """Look at the top three cards of your library, then put them back in
    any order. You may shuffle. Draw a card.

    — Ponder. Reuses the existing non-interactive `scry` resolution exactly
    as `RulesEngine.scry` already documents it (a goldfish/solo session has
    no chooser, so it deterministically keeps every looked-at card on top
    in its existing order) — "put them back in any order" and "you may
    shuffle" both have "leave everything exactly as it is" among their
    legal outcomes, so ``scry(3)`` already resolves Ponder correctly at
    this engine's fidelity; a literal "always shuffle" would be a
    *different*, wrong resolution (shuffling is optional, not automatic).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("scry", {"count": 3}), EffectSpec("draw", {"count": 1})],
        )
    ]


register("Ponder", _ponder)
