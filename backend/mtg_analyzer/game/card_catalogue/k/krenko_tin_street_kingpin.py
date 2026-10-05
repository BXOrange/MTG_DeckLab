from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _krenko_tin_street_kingpin() -> list[AbilitySpec]:
    """Whenever this creature attacks, put a +1/+1 counter on it, then
    create a number of 1/1 red Goblin creature tokens equal to Krenko's
    power.

    — Krenko, Tin Street Kingpin. RULE 608.2: the counter lands first, so
    the `bind` measures the *post-counter* power (`characteristic` of the
    source, read when the bind node runs, after the `add_counters` before it)
    and substitutes it into the token count.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "add_counters", "params": {"amount": 1, "kind": "+1/+1", "target_kind": None}},
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "characteristic", "characteristic": "power", "of": "self"},
                    "effects": [{"type": "create_token", "params": {
                        "count": "$n", "power": 1, "toughness": 1, "colors": ["R"],
                        "subtypes": ["Goblin"], "token_name": "Goblin",
                    }}],
                }},
            ]})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Krenko, Tin Street Kingpin", _krenko_tin_street_kingpin)
