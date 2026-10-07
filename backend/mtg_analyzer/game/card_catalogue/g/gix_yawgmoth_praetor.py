from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gix_yawgmoth_praetor() -> list[AbilitySpec]:
    """Whenever a creature deals combat damage to one of your opponents, its controller may pay 1 life. If they do, they draw a card.
    {4}{B}{B}{B}, Discard X cards: Exile the top X cards of target opponent's library. You may play lands and cast spells from among cards exiled this way without paying their mana costs.

    — PLAY-ALL (Mardu Surge). Combat damage asks the damaging creature's
    controller to pay life and draw. The activation pays its discard-X cost,
    exiles the targeted opponent's top X cards, then offers repeated free
    casts and ordinary legal land plays only during this resolution.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "Pay 1 life", "payer": "trigger_subject_controller",
                "prompt": "1 Leben zahlen, um eine Karte zu ziehen?",
                "effects": [{"type": "draw", "params": {"count": 1}}],
            })],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "recipient_is_opponent": True,
                              "filter": {"card_type": "creature"}},
                "filter": {"combat": True, "is_player": True},
            },
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile_top_of_library", {
                    "player_selector": "target", "target_kind": "opponent",
                    "count": {"kind": "x_paid", "of": "source"},
                }),
                EffectSpec("grant_conditional_cast_from_exile", {
                    "all_cards": True, "during_resolution": True,
                }),
            ],
            cost={"text": "{4}{B}{B}{B}, Discard X cards"},
        ),
    ]


register("Gix, Yawgmoth Praetor", _gix_yawgmoth_praetor)
