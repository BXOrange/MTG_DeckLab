from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _demonic_hordes() -> list[AbilitySpec]:
    """{T}: Destroy target land.
    At the beginning of your upkeep, unless you pay {B}{B}{B}, tap Demonic Hordes and sacrifice a land of an
    opponent's choice.

    The "unless you pay" is `pay_cost_then` with only an ``else`` branch (MEC-118).  The land is *not* targeted --
    RULE 701.17a, the opponent picks as the trigger resolves -- so `sacrifice` takes ``chooser="opponent"`` (the
    sacrificing player stays the controller; with several opponents the controller names who picks).
    """
    return [
        AbilitySpec("activated", [EffectSpec("destroy", {"target_kind": "land"})], cost={"text": "{T}"}),
        AbilitySpec("triggered", [
            EffectSpec("pay_cost_then", {
                "cost": "{B}{B}{B}",
                "effects": [],
                "else_effects": [
                    {"type": "tap", "params": {"target_kind": "source", "untap": False}},
                    {"type": "sacrifice", "params": {
                        "selector": "controller", "what": "land", "count": 1, "chooser": "opponent",
                    }},
                ],
            }),
        ], trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"}),
    ]


register("Demonic Hordes", _demonic_hordes)
