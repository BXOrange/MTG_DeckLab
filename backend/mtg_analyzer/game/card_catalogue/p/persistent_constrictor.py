from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _persistent_constrictor() -> list[AbilitySpec]:
    """At the beginning of each opponent's upkeep, they lose 1 life and you put a -1/-1 counter on up to one target creature they control.
    Persist (When this creature dies, if it had no -1/-1 counters on it, return it to the battlefield under its owner's control with a -1/-1 counter on it.)

    — PLAY-ALL (Endless Punishment). Persist is the keyword. The trigger is the parser's "they lose 1 life" (``player: active_player``) plus a `add_counters`
    of -1/-1 on an optional ``creature_that_player_controls`` (the "that player" kind the upkeep head names — the active player).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 1, "player": "active_player"}),
                EffectSpec("add_counters", {"count": 1, "kind": "-1/-1", "target_kind": "creature_that_player_controls", "optional": True}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "not_you"},
        ),
    ]


register("Persistent Constrictor", _persistent_constrictor)
