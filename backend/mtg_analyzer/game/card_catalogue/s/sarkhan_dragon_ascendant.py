from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sarkhan_dragon_ascendant() -> list[AbilitySpec]:
    """When Sarkhan enters, you may behold a Dragon. If you do, create a Treasure token. (To behold a
    Dragon, choose a Dragon you control or reveal a Dragon card from your hand.)
    Whenever a Dragon you control enters, put a +1/+1 counter on Sarkhan. Until end of turn, Sarkhan
    becomes a Dragon in addition to his other types and gains flying.

    — Reign of Dragons deck batch. The ETB is `behold_then` (`BeholdThenEffect`: behold, then the
    Treasure). The Dragon trigger is a group ETB whose body is a +1/+1 counter on himself and a
    resolve-time `grant_until` on himself (the Nogi shape: a Dragon type addition and flying until end
    of turn).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("behold_then", {"quality": "Dragon", "effects": [
                {"type": "create_token", "params": {"count": 1, "token_name": "Treasure"}},
            ]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"kind": "+1/+1", "count": 1, "target_kind": None}),
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {"add_subtypes": ["Dragon"]}},
                    "extra_statics": [{"type": "grant_keyword", "params": {"keywords": ["flying"]}}],
                    "duration": "end_of_turn", "target_kind": None, "self_subject": True,
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD,
                     "condition": {"subject": "group", "controller": "you", "subtypes": ["dragon"]}},
        ),
    ]


register("Sarkhan, Dragon Ascendant", _sarkhan_dragon_ascendant)
