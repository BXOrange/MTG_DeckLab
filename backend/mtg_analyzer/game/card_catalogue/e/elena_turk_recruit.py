from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _elena_turk_recruit() -> list[AbilitySpec]:
    """When Elena enters, return target non-Assassin historic card from your graveyard to your hand. (Artifacts, legendaries, and Sagas are historic.)
    Whenever you cast a historic spell, put a +1/+1 counter on Elena.

    — PLAY-ALL (Limit Break). The cast trigger is the parser's claim (an ``any_of`` historic spell filter). The enters trigger is `return_from_graveyard` over the new
    ``graveyard_non_assassin_historic`` kind (artifact, legendary or Saga, not an Assassin).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_non_assassin_historic", "destination": "hand"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_filter": {"any_of": [{"card_type": "artifact"}, {"legendary": True}, {"subtype": "saga"}]},
            },
        ),
    ]


register("Elena, Turk Recruit", _elena_turk_recruit)
