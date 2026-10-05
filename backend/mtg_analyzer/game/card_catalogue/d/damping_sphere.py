from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _damping_sphere() -> list[AbilitySpec]:
    """If a land is tapped for two or more mana, it produces {C} instead of
    any other type and amount.
    Each spell a player casts costs {1} more to cast for each other spell
    that player has cast this turn.

    — MEC-36. Two independent unscoped statics, neither previously
    reachable. The first is a new `StaticAbility` layer,
    `"mana_type_override"`, consulted directly by `GameEngine.
    tap_for_mana` (`continuous.mana_type_override_for`) right alongside
    the already-shipped `mana_multiplier` (Nyxbloom Ancient) — a boolean
    override on the *true*, post-multiplier produced total, not a layer-6
    ability grant. The second is `cost_reduction`'s existing `per`
    count-selector vocabulary widened with a new `"spells_cast_this_turn"`
    key: `continuous._cost_static_amount` already evaluates `per` against
    the *casting* player (not this static's own controller), and
    `RulesEngine._track_spell_cast` increments `GameState.spells_cast_
    this_turn` strictly after cost is computed for the spell just cast —
    so "for each other spell" falls out for free with no off-by-one
    correction needed. That field's own reset had to widen from
    "just the incoming active player" (its original RULE 731.2-only
    scope) to every player, every turn, since a non-active player's own
    running total needs to stay accurate too.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("mana_type_override", {"min_amount": 2, "to": "C"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "all_spells",
                "generic": 1,
                "increase": True,
                "per": "spells_cast_this_turn",
            })],
        ),
    ]


register("Damping Sphere", _damping_sphere)
