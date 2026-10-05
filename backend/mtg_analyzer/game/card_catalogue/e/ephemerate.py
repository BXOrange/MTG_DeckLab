from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ephemerate() -> list[AbilitySpec]:
    """Exile target creature you control, then return it to the
    battlefield under its owner's control.
    Rebound (If you cast this spell from your hand, exile it as it
    resolves. At the beginning of your next upkeep, you may cast this
    card from exile without paying its mana cost.)

    — Ephemerate. Rebound (RULE 702.88b) is now modeled, reusing the
    `create_delayed_trigger`/`GameState.delayed_triggers` primitive Mana
    Drain's own batch built (this docstring previously deferred it as
    blocked on exactly that primitive, citing Mana Drain among others —
    stale the moment that batch shipped; see `AbilitySpec.rebound`'s
    docstring for the "standing free-cast window instead of a forced
    yes/no choice" simplification). The `rebound` marker rides on its own
    empty-effects spec, the same "scan every spec" shape `impulsive_draw_
    on_combat_damage` uses; the blink half is unchanged (`game/effects/core.py`'s
    `BlinkEffect`/`RulesEngine.blink`, RULE 400.7's "exile then immediately
    return").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("blink", {"target_kind": "creature_you_control"})],
        ),
        AbilitySpec(
            "static",
            [],
            rebound=True,
        ),
    ]


register("Ephemerate", _ephemerate)
