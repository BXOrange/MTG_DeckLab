from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _smothering_tithe() -> list[AbilitySpec]:
    """Whenever an opponent draws a card, that player may pay {2}. If the
    player doesn't, you create a Treasure token.

    MEC-12 — the same tax-draw family as Rhystic Study/Mystic Remora/Esper
    Sentinel above, but the trigger event is `EventType.DRAW` (an
    ``"opponent draws"`` group condition needed its own
    `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` entry, ``DRAW``:
    ``"player_id"`` — `RulesEngine.draw` already fired that event with the
    right shape, only this table row was missing) and the "if you don't"
    branch is a Treasure, not a card — `effects.PayCostThenEffect`'s
    general RULE 118.3 "you may pay `<cost>`. If you don't, `<effect>`."
    shape (``payer="event_player"`` reads the *drawing* player off the
    triggering DRAW event, same as `TaxedDrawEffect`'s payer read for its
    own family; the create-token effect resolves under this permanent's
    own controller, matching "**you** create a Treasure token").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec(
                "pay_cost_then",
                {
                    "cost": "{2}",
                    "payer": "event_player",
                    "else_effects": [
                        {
                            "type": "create_token",
                            "params": {"token_name": "Treasure", "count": 1},
                        }
                    ],
                },
            )],
            trigger={
                "event": EventType.DRAW,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        )
    ]


register("Smothering Tithe", _smothering_tithe)
