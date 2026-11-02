from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Note names for the opponent's secret answer and your guess (`GameObject.guess_notes`), and the two answers a
#: true/false statement can have.
_SECRET, _GUESS = "secret", "guess"
_TRUE, _FALSE = "true", "false"
_TRUE_FALSE = [{"id": _TRUE, "label": "Wahr"}, {"id": _FALSE, "label": "Falsch"}]


def _note_is(note: str, value: str) -> dict:
    return {"kind": "guess_note_is", "note": note, "answer": value}


def _blufferfish() -> list[AbilitySpec]:
    """{3}{U}: An opponent tells you a statement about themselves and secretly notes whether it's true or false. You guess which it is. If you guessed correctly, this creature gets +2/+0 and can't be blocked this turn.

    RULE 608.2d / 400.2: the statement itself is spoken out of game; the engine needs the two closed answers. The
    opponent records true/false first (a hidden note on this creature, never in any view), then you guess; a matching
    pair runs the `pump` and `unblockable` of the body.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("seq", {"effects": [
                {"type": "ask_player", "params": {
                    "note": _SECRET, "player": "opponent", "options": _TRUE_FALSE,
                    "prompt": "Nenne eine Aussage über dich und notiere heimlich, ob sie wahr oder falsch ist",
                }},
                {"type": "ask_player", "params": {
                    "note": _GUESS, "player": "controller", "options": _TRUE_FALSE,
                    "prompt": "Rate: War die Aussage wahr oder falsch?",
                }},
                {"type": "if_else", "params": {
                    "condition": {"kind": "any", "conditions": [
                        {"kind": "all", "conditions": [_note_is(_SECRET, _TRUE), _note_is(_GUESS, _TRUE)]},
                        {"kind": "all", "conditions": [_note_is(_SECRET, _FALSE), _note_is(_GUESS, _FALSE)]},
                    ]},
                    "then": [
                        {"type": "pump", "params": {"power": 2, "toughness": 0}},
                        {"type": "unblockable", "params": {"target_kind": None}},
                    ],
                    "else": [],
                }},
            ]})],
            cost={"mana": "{3}{U}"},
        ),
    ]


register("Blufferfish", _blufferfish)
