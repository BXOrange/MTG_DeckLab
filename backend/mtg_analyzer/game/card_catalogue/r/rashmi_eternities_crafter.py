from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rashmi_eternities_crafter() -> list[AbilitySpec]:
    """Whenever you cast your first spell each turn, reveal the top card of your library. You may cast it without paying its mana cost if it's a spell with lesser mana value. If you don't cast it, put it into your hand.

    — PLAY-ALL (Jump Scare!). The head is the parser's "first spell each turn" trigger (``is_nth_spell_cast_this_turn``).
    The body is Powerbalance's reveal/`cast_revealed_free` shape: `reveal_top`, then — when the revealed card is a
    nonland card of lesser mana value than the cast spell (the SPELL_CAST event's ``mana_value``) — the optional free cast,
    then `put_revealed_card` (a no-op once the card has left the top of the library, so it only moves a card that
    was not cast).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "reveal_top", "params": {"whose": "you"}},
                {"type": "if_else", "params": {
                    "condition": {"kind": "all", "conditions": [
                        {"kind": "not", "condition": {"kind": "is_card_type", "of": "revealed", "card_type": "land"}},
                        {"kind": "amount_compare", "op": "lt",
                         "left": {"kind": "characteristic", "characteristic": "mana_value", "of": "revealed"},
                         "right": {"kind": "trigger_event", "field": "mana_value"}},
                    ]},
                    "then": [{"type": "cast_revealed_free", "params": {}}],
                    "else": [],
                }},
                {"type": "put_revealed_card", "params": {"destination": "hand"}},
            ]})],
            trigger={"event": "SPELL_CAST", "condition": {"subject": "you"}, "is_nth_spell_cast_this_turn": 1},
        ),
    ]


register("Rashmi, Eternities Crafter", _rashmi_eternities_crafter)
