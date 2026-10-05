from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Currency Converter ("exiled with this" cash-out) — PAR-60
# ===========================================================================
# Reuse of MEC-21's `GameObject.exiled_with_ids` accumulating tracker
# (Agatha's Soul Cauldron). The discard trigger now feeds it via
# `ExileTriggeringDiscardMayPlayThisTurnEffect`'s new ``track_exiled_with``
# (``play_permission`` off — Currency Converter grants no play window); the
# new `currency_converter_cash_out` effect reads it back.


def _currency_converter() -> list[AbilitySpec]:
    """Whenever you discard a card, you may exile that card from your
    graveyard.
    {2}, {T}: Draw a card, then discard a card.
    {T}: Put a card exiled with this artifact into its owner's graveyard. If
    it's a land card, create a Treasure token. If it's a nonland card,
    create a 2/2 black Rogue creature token.

    Documented simplification: the discard-exile "you may" is modeled as
    makes) — banking a just-discarded card for the {T} payoff is what this
    card wants every time."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_triggering_discard_may_play_this_turn", {
                "play_permission": False, "track_exiled_with": True,
            })],
            trigger={"event": EventType.DISCARD_CARD, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1}), EffectSpec("discard", {"count": 1})],
            cost={"text": "{2}, {T}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("currency_converter_cash_out", {})],
            cost={"text": "{T}"},
        ),
    ]


register("Currency Converter", _currency_converter)
