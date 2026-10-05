from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _twitching_doll() -> list[AbilitySpec]:
    """{T}: Add one mana of any color. Put a nest counter on this creature.
    {T}, Sacrifice this creature: Create a 2/2 green Spider creature token
    with reach for each counter on this creature. Activate only as a
    sorcery.

    — PLAY-ALL Step 2 (Raggadragga). The mana half of the first line is read
    off the card's oracle text (`mana_abilities_for`), independent of this
    entry — but that reader has no generic "put a counter" rider (only rad
    counters), so the nest counter is a triggered mana ability on this
    creature's own `TAPPED_FOR_MANA` (RULE 605.1b, resolving off-stack at
    once, like Wild Growth's), which is the same observable result. The
    second ability is a sacrifice-as-cost `create_token` whose ``count`` is the
    `counters` amount operand over this creature's nest counters, with the
    sorcery-speed marker (Ozolith's shape).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "nest"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA, "condition": {"subject": "self"},
                "mana_ability": True,
            },
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("create_token", {
                    "count": {"kind": "counters", "counter": "nest"},
                    "power": 2, "toughness": 2, "colors": ["G"],
                    "subtypes": ["Spider"], "keywords": ["reach"], "token_name": "Spider",
                }),
                EffectSpec("sorcery_speed_marker", {}),
            ],
            cost={"text": "{T}, Sacrifice ~"},
        ),
    ]


register("Twitching Doll", _twitching_doll)
