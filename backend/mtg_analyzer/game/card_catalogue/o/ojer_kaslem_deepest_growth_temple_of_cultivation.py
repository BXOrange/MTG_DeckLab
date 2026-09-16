from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ojer_kaslem_deepest_growth() -> list[AbilitySpec]:
    """Trample
    Whenever Ojer Kaslem deals combat damage to a player, reveal that
    many cards from the top of your library. You may put a creature card
    and/or a land card from among them onto the battlefield. Put the rest
    on the bottom in a random order.
    When Ojer Kaslem dies, return it to the battlefield tapped and
    transformed under its owner's control.

    — Ojer Kaslem, Deepest Growth, the third of the cycle and, like Ojer
    Taq, previously `UNMODELED` end-to-end for the same reason (one
    never-before-modeled clause blocking the death trigger too). The
    combat-damage clause is a first-of-its-kind template (no cached card
    shares this "reveal N, up to one creature *and* up to one land, rest
    to bottom" shape) — new `RevealTopThenCreatureAndOrLandBattlefieldEffect`
    (`amount_from_trigger_event="amount"` off the firing DAMAGE event, the
    same idiom Ragavan/Imodane-shaped triggers already use), whose own
    docstring explains why the "and/or" can't be one `request_choose_
    objects` call (only one `pending_choice` at a time) and instead chains
    into a second, `then_specs`/`else_specs`-driven pick
    (`OjerKaslemLandPickEffect`) — the same continuation shape `ScrollRack
    Effect`/`ScrollRackFinishEffect` already established for "decide now,
    act once the player answers". The trigger condition mirrors Ragavan,
    Nimble Pilferer's own "self deals combat damage to a player" shape
    exactly. The death trigger is again the shared `return_self_from_
    graveyard_untargeted` shape.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("reveal_top_then_creature_and_or_land_battlefield", {
                "amount_from_trigger_event": "amount",
            })],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_from_graveyard_untargeted", {
                "destination": "battlefield", "tapped": True, "transformed": True,
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
        ),
    ]


register("Ojer Kaslem, Deepest Growth // Temple of Cultivation", _ojer_kaslem_deepest_growth)
