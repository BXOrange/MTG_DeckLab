from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _baral_and_kari_zev() -> list[AbilitySpec]:
    """First strike, menace
    Whenever you cast your first instant or sorcery spell each turn, you may cast a spell with
    lesser mana value that shares a card type with it from your hand without paying its mana
    cost. If you don't, create First Mate Ragavan, a legendary 2/1 red Monkey Pirate creature
    token. It gains haste until end of turn.

    — Jeskai Striker deck batch. First strike/menace are keywords. The trigger is a `SPELL_CAST` by
    you gated by the new ``is_nth_instant_or_sorcery_cast_this_turn`` (the per-type sibling of
    ``is_nth_spell_cast_this_turn``). The body is the Expertise cycle's `free_cast_from_hand`
    (Kellan's shape) with ``strictly_less_than_trigger`` and ``shares_type_with_trigger``; its
    ``else_effects`` is the "if you don't" token. **Documented simplification:** the token has
    haste printed on it rather than "until end of turn" — haste only matters on the turn it
    enters, so the difference is unobservable.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("free_cast_from_hand", {
                "mana_value_from_trigger": True, "strictly_less_than_trigger": True,
                "shares_type_with_trigger": True,
                "else_effects": [{"type": "create_token", "params": {
                    "count": 1, "token_name": "First Mate Ragavan", "power": 2, "toughness": 1,
                    "colors": ["R"], "subtypes": ["Monkey", "Pirate"], "legendary": True,
                    "keywords": ["haste"],
                }}],
            })],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_card_types": ["instant", "sorcery"],
                "is_nth_instant_or_sorcery_cast_this_turn": 1,
            },
        ),
    ]


register("Baral and Kari Zev", _baral_and_kari_zev)
