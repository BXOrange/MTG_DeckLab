from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ripples_of_potential() -> list[AbilitySpec]:
    """Proliferate, then choose any number of permanents you control that had
    a counter put on them this way. Those permanents phase out. (To
    proliferate, choose any number of permanents and/or players, then give
    each another counter of each kind already there. Treat phased-out
    permanents and anything attached to them as though they don't exist until
    their controller's next turn.)

    — PLAY-ALL Step 2 (Counter Intelligence). `proliferate` now records which
    permanents it gave a counter (`GameContext.proliferated_objects`); the new
    `phase_out_proliferated` offers the controller's own among them as an
    optional pick-any-number (`choose_objects` action ``phase_out``). The
    proliferate half keeps its documented MVP simplification (it hits every
    counter-bearing permanent and player, no chooser), so the phase-out pool is
    all of *your* counter-bearing permanents.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("proliferate", {}),
                EffectSpec("phase_out_proliferated", {}),
            ],
        ),
    ]


register("Ripples of Potential", _ripples_of_potential)
