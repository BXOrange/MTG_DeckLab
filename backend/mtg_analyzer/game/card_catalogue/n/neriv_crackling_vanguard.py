from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _neriv_crackling_vanguard() -> list[AbilitySpec]:
    """Flying, deathtouch
    When Neriv enters, create two 1/1 red Goblin creature tokens.
    Whenever Neriv attacks, exile a number of cards from the top of your library equal to the number of differently named tokens you control. During any turn you attacked with a commander, you may play those cards.

    — Neriv, Crackling Vanguard. Flying/deathtouch come from the keyword catalogue, the ETB is the parser's. The
    attack trigger is Evendo Brushrazer's idiom: `exile_top_of_library` (``track_exiled_with``) followed by
    `grant_conditional_cast_from_exile` — a standing, never-expiring "may play" (lands included) gated on
    `event_this_turn`, here an `ATTACKERS_DECLARED` of ours whose attackers include a commander. The count is a
    structured selector over tokens you control with ``distinct="name"``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 1, "colors": ["R"], "subtypes": ["Goblin"],
                "token_name": "Goblin",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_top_of_library", {
                    "count": {"kind": "count_selector", "selector": {
                        "zone": "battlefield", "of": "you", "filter": {"token": True}, "distinct": "name",
                    }},
                    "track_exiled_with": True,
                }),
                EffectSpec("grant_conditional_cast_from_exile", {
                    "all_cards": True, "linked_source": True,
                    "condition": {"kind": "event_this_turn", "min": 1, "trigger": {
                        "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                        "attackers_declared": {"filter": {"is_commander": True}, "min": 1},
                    }},
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Neriv, Crackling Vanguard", _neriv_crackling_vanguard)
