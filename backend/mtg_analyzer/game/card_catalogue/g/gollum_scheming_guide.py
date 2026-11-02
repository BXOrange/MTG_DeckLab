from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Note names: the kind you choose, and the kind the opponent predicts the top card is.
_KIND, _GUESS = "kind", "guess"
_LAND, _NONLAND = "land", "nonland"


def _ask_opponent(prompt: str, yes: str, no: str) -> dict:
    """The opponent's yes/no on "is it the chosen kind?", stored as the *kind it predicts* (yes -> chosen kind)."""
    return {"type": "ask_player", "params": {
        "note": _GUESS, "player": "opponent", "prompt": prompt,
        "options": [{"id": yes, "label": "Ja"}, {"id": no, "label": "Nein"}],
    }}


def _gollum_scheming_guide() -> list[AbilitySpec]:
    """Whenever Gollum attacks, look at the top two cards of your library, put them back in any order, then choose land or nonland. An opponent guesses whether the top card of your library is the chosen kind. Reveal that card. If they guessed right, remove Gollum from combat. Otherwise, you draw a card and Gollum can't be blocked this turn.

    RULE 608.2d: `look_reorder_top` / `ask_player` / `reveal_top` compose in a `seq`; the opponent's yes/no is stored as
    the kind it predicts, so "guessed right" is whether the revealed card is of that kind (RULE 701.20: reveal first,
    compare after). A wrong guess draws and `unblockable`; a right one is `remove_from_combat` (RULE 506.4).
    """
    guessed_right = {"kind": "any", "conditions": [
        {"kind": "all", "conditions": [
            {"kind": "guess_note_is", "note": _GUESS, "answer": _LAND},
            {"kind": "is_card_type", "of": "revealed", "card_type": "land"},
        ]},
        {"kind": "all", "conditions": [
            {"kind": "guess_note_is", "note": _GUESS, "answer": _NONLAND},
            {"kind": "not", "condition": {"kind": "is_card_type", "of": "revealed", "card_type": "land"}},
        ]},
    ]}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "look_reorder_top", "params": {"count": 2}},
                {"type": "ask_player", "params": {
                    "note": _KIND, "player": "controller", "prompt": "Wähle Land oder Nichtland",
                    "options": [{"id": _LAND, "label": "Land"}, {"id": _NONLAND, "label": "Nichtland"}],
                }},
                {"type": "if_else", "params": {
                    "condition": {"kind": "guess_note_is", "note": _KIND, "answer": _LAND},
                    "then": [_ask_opponent("Ist die oberste Karte der Bibliothek ein Land?", _LAND, _NONLAND)],
                    "else": [_ask_opponent("Ist die oberste Karte der Bibliothek ein Nichtland?", _NONLAND, _LAND)],
                }},
                {"type": "reveal_top", "params": {"whose": "you"}},
                {"type": "if_else", "params": {
                    "condition": guessed_right,
                    "then": [{"type": "remove_from_combat", "params": {"target_kind": None}}],
                    "else": [
                        {"type": "draw", "params": {"count": 1}},
                        {"type": "unblockable", "params": {"target_kind": None}},
                    ],
                }},
            ]})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Gollum, Scheming Guide", _gollum_scheming_guide)
