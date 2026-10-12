from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _yuffie_materia_hunter() -> list[AbilitySpec]:
    """Ninjutsu {1}{R} ({1}{R}, Return an unblocked attacker you control to hand: Put this card onto the battlefield from your hand tapped and attacking.)
    When Yuffie enters, gain control of target noncreature artifact for as long as you control Yuffie. Then you may attach an Equipment you control to Yuffie.

    — PLAY-ALL (Limit Break). Ninjutsu is the keyword. The enters trigger is Pyreswipe Hawk's `grant_until` layer-2 ``control_change`` bounded by ``source_controlled_by_you``
    (Thancred Waters' "for as long as you control ~": the control effect ends once Yuffie leaves or another player controls her), over a noncreature artifact, then the new `attach_equipment` onto Yuffie (an
    optional single Equipment you control).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("grant_until", {
                    "static": {"type": "control_change", "params": {}},
                    "target_kind": "noncreature_artifact", "optional": True,
                    "condition": {"kind": "source_controlled_by_you"},
                }),
                EffectSpec("attach_equipment", {"to_source": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Yuffie, Materia Hunter", _yuffie_materia_hunter)
