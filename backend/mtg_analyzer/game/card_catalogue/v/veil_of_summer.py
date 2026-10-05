from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _veil_of_summer() -> list[AbilitySpec]:
    """Draw a card if an opponent has cast a blue or black spell this
    turn. Spells you control can't be countered this turn. You and
    permanents you control gain hexproof from blue and from black until
    end of turn. (You and they can't be the targets of blue or black
    spells or abilities your opponents control.)

    — MEC-12 (cEDH Kinnan). **Documented simplification**: the third
    sentence ("You and permanents you control gain hexproof from blue
    and from black") is dropped — this engine's `combat.has_hexproof`
    is an unqualified RULE 702.11b flag with no "hexproof from `<quality>`"
    variant (RULE 702.11c), and there is no player-level hexproof/
    targetability check anywhere at all yet (every "player" target kind
    in `targeting.py` returns every living player unconditionally).
    Building qualified hexproof for both permanents and players is a
    real, standalone engine primitive, not something to wedge into this
    card's own entry. The other two clauses are real: the new
    ``opponent_cast_color_this_turn`` `ConditionalEffect` condition
    (`GameState.spell_colors_cast_this_turn`, tracked off `SPELL_CAST`
    the same way `cast_instant_or_sorcery_this_turn` already is) and the
    new `cant_be_countered_this_turn` (an `UncounterableGrant` — a rule for
    the rest of the turn, so it covers a spell already on the stack too).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec(
                    "draw", {"count": 1},
                    condition={"opponent_cast_color_this_turn": ["U", "B"]},
                ),
                EffectSpec("cant_be_countered_this_turn", {}),
            ],
        ),
    ]


register("Veil of Summer", _veil_of_summer)
