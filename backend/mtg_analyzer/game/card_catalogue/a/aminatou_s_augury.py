from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aminatou_s_augury() -> list[AbilitySpec]:
    """Exile the top eight cards of your library. You may put a land card from among them onto the battlefield. Until end of turn, for each nonland card type, you may cast a spell of that type from among the exiled cards without paying its mana cost.

    — PLAY-ALL (Miracle Worker). The new `aminatous_augury`: the eight cards are exiled, the optional land goes onto the battlefield, and
    every nonland card is armed for a free cast this turn inside one type-slot pool (casting a spell spends one slot of its types; a
    card left without an open slot stops being free).
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("aminatous_augury", {})]),
    ]


register("Aminatou's Augury", _aminatou_s_augury)
