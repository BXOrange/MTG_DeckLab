from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Note name of the "do you reveal?" answer and its two answers.
_REVEAL_NOTE = "reveal_top"
_REVEAL, _DECLINE = "reveal", "keep_hidden"


def _b_elanna_torres_scrapper() -> list[AbilitySpec]:
    "Vigilance, trample\n{2}, {T}: Surveil 2, then you may reveal the top card of your library. If an artifact card is revealed this way, draw a card. If you don't draw a card this way, put two +1/+1 counters on B'Elanna Torres."
    # RULE 701.31 surveil, then RULE 608.2d: the optional reveal is a yes/no answer; RULE 701.20 the reveal itself.
    # "If you don't draw a card this way" covers declining to reveal and revealing a non-artifact alike.
    put_counters = {"type": "add_counters", "params": {"amount": 2, "target_kind": None}}
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("surveil", {"count": 2}),
                EffectSpec("seq", {"effects": [
                    {"type": "ask_player", "params": {
                        "note": _REVEAL_NOTE, "player": "controller", "prompt": "Oberste Karte aufdecken?",
                        "options": [{"id": _REVEAL, "label": "Aufdecken"}, {"id": _DECLINE, "label": "Nicht aufdecken"}],
                    }},
                    {"type": "if_else", "params": {
                        "condition": {"kind": "guess_note_is", "note": _REVEAL_NOTE, "answer": _REVEAL},
                        "then": [
                            {"type": "reveal_top", "params": {"whose": "you"}},
                            {"type": "if_else", "params": {
                                "condition": {"kind": "is_card_type", "of": "revealed", "card_type": "artifact"},
                                "then": [{"type": "draw", "params": {"count": 1}}],
                                "else": [put_counters],
                            }},
                        ],
                        "else": [put_counters],
                    }},
                ]}),
            ],
            cost={"mana": "{2}", "taps_self": True},
        ),
    ]


register("B'Elanna Torres, Scrapper", _b_elanna_torres_scrapper)
