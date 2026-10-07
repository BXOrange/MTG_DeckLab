from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _primordial_mist() -> list[AbilitySpec]:
    """At the beginning of your end step, you may manifest the top card of your library. (Put it onto the battlefield face down as a 2/2 creature. Turn it face up any time for its mana cost if it's a creature card.)
    Exile a face-down permanent you control face up: You may play that card this turn. (You still pay its costs. Timing rules still apply.)

    The selected face-down permanent is exiled as a cost; permission resolves separately.
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
            [EffectSpec("play_cards_exiled_with_source", {"from_activation_cost": True})],
            cost={"text": "", "exile_others": [1, "face_down"]},
        ),
    ]


register("Primordial Mist", _primordial_mist)
