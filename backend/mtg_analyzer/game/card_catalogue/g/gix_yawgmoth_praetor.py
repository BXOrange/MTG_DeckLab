from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gix_yawgmoth_praetor() -> list[AbilitySpec]:
    """Whenever a creature deals combat damage to one of your opponents, its controller may pay 1 life. If they do, they draw a card.
    {4}{B}{B}{B}, Discard X cards: Exile the top X cards of target opponent's library. You may play lands and cast spells from among cards exiled this way without paying their mana costs.

    — Gix, Yawgmoth Praetor. The first ability is a group `DAMAGE` trigger over *any* creature (no controller
    scope) hitting one of Gix's controller's opponents; a free-form `pay_cost_then` asks the damaging creature's
    controller (new ``payer="trigger_subject_controller"``) for the life, and the draw is theirs
    (`player: {"of": "entering", "as": "controller"}`). The activation is Evendo Brushrazer's exile-and-grant idiom:
    `exile_top_of_library` over a real "target opponent" and an X measured as `x_paid` (the discard cost is
    ``Discard X cards``), then `grant_conditional_cast_from_exile` — a standing permission (lands included) with the
    new ``cost_override="{0}"`` for "without paying their mana costs". **Documented simplification:** a spell cast
    from exile this way is cast as an ordinary hard cast with a zero cost, so a card with an X in its cost has X = 0.
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
                    "all_cards": True, "condition": {}, "cost_override": "{0}",
                }),
            ],
            cost={"text": "{4}{B}{B}{B}, Discard X cards"},
        ),
    ]


register("Gix, Yawgmoth Praetor", _gix_yawgmoth_praetor)
