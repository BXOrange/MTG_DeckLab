from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _primordial_mist() -> list[AbilitySpec]:
    """At the beginning of your end step, you may manifest the top card of your library. (Put it onto the battlefield face down as a 2/2 creature. Turn it face up any time for its mana cost if it's a creature card.)
    Exile a face-down permanent you control face up: You may play that card this turn. (You still pay its costs. Timing rules still apply.)

    — PLAY-ALL (Jump Scare!). The end-step manifest is the parser's. The second ability is a `choose_objects` over your
    face-down permanents with the new ``exile_face_down_for_play`` action: the pick is exiled (face up, RULE 708.9) and
    granted a same-turn play permission. **Simplification:** the exile is made as the ability resolves rather than paid as
    a cost, so it can be responded to; the activation is only offered while you control a face-down permanent.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("manifest", {"count": 1, "kind": "manifest"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
            optional=True,
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("choose_objects", {
                "action": "exile_face_down_for_play", "what": "face_down", "count": 1,
                "prompt": "Verdeckte Permanente offen ins Exil schicken",
            })],
            cost={"text": "", "activation_condition": {
                "kind": "control_count", "min": 1,
                "selector": {"zone": "battlefield", "of": "you", "filter": {"face_down": True}},
            }},
        ),
    ]


register("Primordial Mist", _primordial_mist)
