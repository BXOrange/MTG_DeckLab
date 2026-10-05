from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _brightcap_badger() -> list[AbilitySpec]:
    """Each Fungus and Saproling you control has "{T}: Add {G}."
    At the beginning of your end step, create a 1/1 green Saproling creature token.

    — Animated Army deck batch (the Fungus Frolic half is an Adventure the card carries). The grant is
    Rishkar's `grant_mana_ability`, one static per creature type (``subtype`` takes a single type), so
    "Fungus and Saproling" is two specs. The end step token is the parser's usual phase-trigger head
    with an inline 1/1 green Saproling.
    """
    def grant(subtype):
        return AbilitySpec("static", [EffectSpec("grant_mana_ability", {
            "mana": [{"G": 1}], "affects": "creatures_you_control", "subtype": subtype,
        })])

    return [
        grant("Fungus"),
        grant("Saproling"),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Saproling", "power": 1, "toughness": 1,
                "colors": ["G"], "subtypes": ["Saproling"],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Brightcap Badger", _brightcap_badger)
register("Brightcap Badger // Fungus Frolic", _brightcap_badger)
