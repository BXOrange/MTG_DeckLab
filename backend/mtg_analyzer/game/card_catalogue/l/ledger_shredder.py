from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ledger_shredder() -> list[AbilitySpec]:
    """Flying
    Whenever a player casts their second spell each turn, this creature
    connives.

    — MEC-43 round 4B. Flying folds in via the ordinary keyword catalogue.
    The trigger shape (``is_nth_spell_cast_this_turn``) already parses on
    its own (Hearthborn Battler's own precedent); what blocked the whole
    card was "connives" itself, RULE 701.47 — draw a card, then discard a
    card, +1/+1 counter if the discard was nonland — genuinely new
    (`ConniveEffect`, `RulesEngine._request_choose_objects`'s new
    ``connive`` flag).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("connive", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group"},
                "is_nth_spell_cast_this_turn": 2,
            },
        ),
    ]


register("Ledger Shredder", _ledger_shredder)
