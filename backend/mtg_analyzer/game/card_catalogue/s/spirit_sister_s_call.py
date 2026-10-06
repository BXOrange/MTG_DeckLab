from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spirit_sister_s_call() -> list[AbilitySpec]:
    """At the beginning of your end step, choose target permanent card in your graveyard. You may sacrifice a permanent that shares a card type with the chosen card. If you do, return the chosen card from your graveyard to the battlefield and it gains "If this permanent would leave the battlefield, exile it instead of putting it anywhere else."

    — PLAY-ALL (Miracle Worker). The new `sacrifice_shared_type_to_return`: the card is the effect's target; the sacrifice is Victimize's optional
    pick restricted to permanents sharing a card type with it, and a paid sacrifice returns the card armed with the exile replacement.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_shared_type_to_return", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Spirit-Sister's Call", _spirit_sister_s_call)
