from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _boss_s_chauffeur() -> list[AbilitySpec]:
    """This creature enters with a number of +1/+1 counters on it equal to one plus the number of other
    creatures you control.
    Alliance — Whenever another creature you control enters, put a +1/+1 counter on this creature.
    When this creature dies, create a 1/1 green and white Citizen creature token for each +1/+1 counter on
    it.

    — Family Matters deck batch. The alliance and dies triggers are the parser's own claims; the entry
    counters are the new `enters_with_counters_count` static (1 + creatures you control, counted as the
    Chauffeur enters, so "other" needs no exclusion).
    """
    return [
        AbilitySpec("static", [EffectSpec("enters_with_counters_count", {
            "kind": "+1/+1", "base": 1, "count_selector": "creatures_you_control",
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": True, "type": "creature"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {"name": "n", "amount": {"kind": "counters", "counter": "+1/+1", "of": "source"},
                                 "effects": [{"type": "create_token", "params": {
                                     "count": "$n", "power": 1, "toughness": 1, "colors": ["G", "W"],
                                     "subtypes": ["Citizen"], "keywords": [], "token_name": "Citizen"}}]})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Boss's Chauffeur", _boss_s_chauffeur)
