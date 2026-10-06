from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lightning_runner() -> list[AbilitySpec]:
    """Double strike, haste
    Whenever this creature attacks, you get {E}{E} (two energy counters), then you may pay eight {E}. If you pay, untap all creatures you control, and after this phase, there is an additional combat phase.

    — PLAY-ALL (Living Energy). Keywords are the catalogue's. One attack trigger: `add_player_counters`, then Aether
    Chaser's `pay_energy_then` over the untap-all (`tap` over the ``creatures_you_control`` selector, as in Moraug) and `extra_combat_phase`.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_player_counters", {"amount": 2, "kind": "energy"}),
                EffectSpec("pay_energy_then", {"amount": 8, "effects": [
                    {"type": "tap", "params": {"selector": "creatures_you_control", "untap": True}},
                    {"type": "extra_combat_phase", "params": {}},
                ]}),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Lightning Runner", _lightning_runner)
