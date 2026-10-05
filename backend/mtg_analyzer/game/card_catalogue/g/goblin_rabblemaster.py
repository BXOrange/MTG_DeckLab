from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _goblin_rabblemaster() -> list[AbilitySpec]:
    """Other Goblin creatures you control attack each combat if able.
    At the beginning of combat on your turn, create a 1/1 red Goblin
    creature token with haste.
    Whenever this creature attacks, it gets +1/+0 until end of turn for
    each other attacking Goblin.

    — Goblin Rabblemaster. The two triggers are what the parser already
    claims for the card; only the first line is hand-written. RULE 508.1a's
    "attacks each combat if able" is the synthetic `attacks_if_able` flag
    keyword `GameEngine._enforce_attacks_if_able` already reads, granted to
    the Goblin group through the ordinary layer-6 `grant_keyword` (the
    parser's `_ATTACKS_IF_ABLE_RE` only knows a self/attached subject).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "subtype": "goblin",
                "keywords": ["attacks_if_able"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "power": 1, "toughness": 1, "colors": ['R'], "subtypes": ['Goblin'], "keywords": ['haste'], "token_name": 'Goblin'})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'begin_combat'}, "phase_relation": 'you'},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec('bind', {"name": 'n', "amount": {'kind': 'count_selector', 'selector': {'zone': 'battlefield', 'of': 'any', 'filter': {'attacking': True, 'subtype': 'goblin', 'not_reference': True}}}, "effects": [{'type': 'pump', 'params': {'power': '$n', 'toughness': 0}}]})],
            trigger={"event": EventType.ATTACKS, "condition": {'subject': 'self'}},
        ),
    ]


register("Goblin Rabblemaster", _goblin_rabblemaster)
