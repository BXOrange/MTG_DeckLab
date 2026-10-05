from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _desperate_gambit() -> list[AbilitySpec]:
    """Choose a source you control and flip a coin. If you win the flip,
    the next time that source would deal damage this turn, it deals
    double that damage instead. If you lose the flip, the next time it
    would deal damage this turn, prevent that damage.

    — Desperate Gambit (MEC-30, last card of the family). A genuinely
    conditional effect-selection shape, not a rider: which of "double" or
    "prevent" applies isn't known until the coin lands, and both branches
    are scoped to the one chosen source rather than the caster's whole
    side. `ChooseSourceCoinFlipEffect` — the chosen-source chooser
    family's third member, narrowed to "a source **you control**" instead
    of "of your choice" — flips the coin only once the pick actually
    resolves and branches into the new `RulesEngine.grant_damage_
    multiplier_from_source` (win, the single-source-scoped sibling of
    `grant_damage_multiplier_this_turn`'s controller-wide shape) or the
    already-shipped `prevent_damage_from_source` (lose). The printed
    "Double" keyword is the ordinary keyword fold-in and needs no separate
    handling — it's just the cached card's own marker for the "deals
    double damage" clause, which the coin-flip branch above already fully
    expresses.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("choose_source_coinflip", {})],
        ),
    ]


register("Desperate Gambit", _desperate_gambit)
