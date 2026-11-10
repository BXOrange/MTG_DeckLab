from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 717: the level a Class ability is gated on (`counters["class_level"]`, 1 on entering).
_LEVEL_TWO, _LEVEL_THREE = 2, 3
#: Damage the level-2 ability deals to each opponent per discard.
_DISCARD_DAMAGE = 2


def _cool_but_rude() -> list[AbilitySpec]:
    """(Gain the next level as a sorcery to add its ability.)
    Whenever you attack, you may discard a card. If you do, draw a card.
    {1}{R}: Level 2
    Whenever you discard a card, this Class deals 2 damage to each opponent.
    {1}{R}: Level 3
    When this Class becomes level 3, search your library for a card, put it into your hand, shuffle, then discard a card at random.

    Hand-authored as a full Class in Paladin Class's pattern: a ``class_level`` level-up activation per level
    (RULE 717.2) and ``min_level`` / ``level_counter`` gates on the level-2 body. The attack loot is the parser's
    own claim. Level 2 is Glint-Horn Buccaneer's ``DISCARD`` trigger. Level 3 is the Class's ``CLASS_LEVEL``
    "becomes level N" trigger (``chapter``) running Gamble's tutor-then-random-discard pair (`search` shuffles
    the library when it is done, RULE 701.19e, before the random discard, RULE 701.8d).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {"cost": "discard a card", "effects": [
                {"type": "draw", "params": {"count": 1}}]})],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": _LEVEL_TWO})],
            cost={"text": "{1}{R}", "sorcery_speed_only": True, "class_level": _LEVEL_TWO},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": _DISCARD_DAMAGE, "selector": "each_opponent"})],
            trigger={
                "event": "DISCARD", "condition": {"subject": "you"},
                "min_level": _LEVEL_TWO, "level_counter": "class_level",
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": _LEVEL_THREE})],
            cost={"text": "{1}{R}", "sorcery_speed_only": True, "class_level": _LEVEL_THREE},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("search", {"criteria": "", "destination": "hand"}),
                EffectSpec("discard", {"count": 1, "random": True}),
            ],
            trigger={"event": EventType.CLASS_LEVEL, "chapter": [_LEVEL_THREE]},
        ),
    ]


register("Cool but Rude", _cool_but_rude)
