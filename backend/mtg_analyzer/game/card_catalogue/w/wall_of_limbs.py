from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wall_of_limbs() -> list[AbilitySpec]:
    """Defender (This creature can't attack.)
    Whenever you gain life, put a +1/+1 counter on this creature.
    {5}{B}{B}, Sacrifice this creature: Target player loses X life, where X is this creature's power.

    — PLAY-ALL (Abzan Armor). Defender is a keyword and the life-gain trigger is the parser's. The sacrifice ability drains a target
    player by the Wall's own power (``source_power``, read from the sacrificed permanent — last-known information).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("lose_life", {
                "target_kind": "player", "amount": {"kind": "count_selector", "selector": "source_power"},
            })],
            cost={"text": "{5}{B}{B}, Sacrifice ~"},
        ),
    ]


register("Wall of Limbs", _wall_of_limbs)
