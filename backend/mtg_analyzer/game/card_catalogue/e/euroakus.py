from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 201.2: lands you control counted by distinct name ("differently named lands"), the selector the parser's
#: count phrase builds for that wording (`parse_count_phrase`).
_DIFFERENTLY_NAMED_LANDS = {"zone": "battlefield", "of": "you", "filter": {"card_type": "land"}, "distinct": "name"}
_WIZARDS_YOU_CONTROL = {"zone": "battlefield", "of": "you", "filter": {"subtype": "wizard"}}


def _euroakus() -> list[AbilitySpec]:
    "When Euroakus enters, create a number of 1/1 blue Human Wizard creature tokens equal to the number of differently named lands you control.\n{4}{G}{U}: Draw a card for each Wizard you control. They each get +1/+1 until end of turn for each card in your hand."
    # RULE 608.2c: the activated ability does its instructions in order, so "each card in your hand" is counted after
    # the draw; "they" is the Wizards you control as the ability resolves (the same group the draw counted).
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": {"kind": "count_selector", "selector": dict(_DIFFERENTLY_NAMED_LANDS)},
                "power": 1, "toughness": 1, "colors": ["U"], "subtypes": ["Human", "Wizard"],
                "token_name": "Human Wizard",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": {"kind": "count_selector", "selector": dict(_WIZARDS_YOU_CONTROL)}}),
                EffectSpec("pump", {
                    "selector": dict(_WIZARDS_YOU_CONTROL),
                    "dynamic_amount": {"kind": "count_selector", "selector": "cards_in_your_hand"},
                }),
            ],
            cost={"mana": "{4}{G}{U}"},
        ),
    ]


register("Euroakus", _euroakus)
