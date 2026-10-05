from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _alchemist_s_talent() -> list[AbilitySpec]:
    """(Gain the next level as a sorcery to add its ability.)
    When this Class enters, create two tapped Treasure tokens.
    {1}{R}: Level 2
    Treasures you control have "{T}, Sacrifice this artifact: Add two mana of any one color."
    {4}{R}: Level 3
    Whenever you cast a spell, if mana from a Treasure was spent to cast it, this Class deals damage
    equal to that spell's mana value to each opponent.

    — Animated Army deck batch. The ETB is the parser's own claim. Level 2 is Goldspan Dragon's
    Treasure grant (`grant_mana_ability`, which replaces the Treasure's printed ability) gated by
    ``min_level``. Level 3 is a `SPELL_CAST` trigger gated by the new ``spell_mana_source_kind``
    (the cast's per-source payment tally) dealing the cast spell's mana value to each opponent.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 2, "token_name": "Treasure", "tapped": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": 2})],
            cost={"text": "{1}{R}", "sorcery_speed_only": True, "class_level": 2},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "permanents_you_control", "subtype": "Treasure",
                "cost": {"text": "{T}, Sacrifice this artifact"},
                "mana": [{color: 2} for color in ("W", "U", "B", "R", "G")],
                "min_level": 2, "level_counter": "class_level",
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": 3})],
            cost={"text": "{4}{R}", "sorcery_speed_only": True, "class_level": 3},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount_from_trigger_event": "mana_value", "selector": "each_opponent"})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_mana_source_kind": "treasure",
                "min_level": 3, "level_counter": "class_level",
            },
        ),
    ]


register("Alchemist's Talent", _alchemist_s_talent)
