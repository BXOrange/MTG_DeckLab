from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _summon_good_king_mog_xii() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after IV.)
    I — Create two 1/2 white Moogle creature tokens with lifelink.
    II, III — Whenever you cast a noncreature spell this turn, create a token that's a copy of a non-Saga token you control.
    IV — Put two +1/+1 counters on each other Moogle you control.
    Flying, lifelink

    The turn-long cast trigger chooses a non-Saga token while resolving, without targeting.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 2, "colors": ["W"], "subtypes": ["Moogle"],
                "keywords": ["lifelink"], "token_name": "Moogle",
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_turn_trigger", {
                "trigger": {
                    "event": "SPELL_CAST", "condition": {"subject": "you"},
                    "spell_filter": {"without_card_type": "creature"},
                },
                "effects": [{"type": "choose_objects", "params": {
                    "action": "select_referent", "what": "permanent", "count": 1,
                    "permanent_filter": {"token": True, "without_subtype": "Saga"},
                    "then": [{"type": "copy_permanent", "params": {"target_kind": None, "referent": "previous"}}],
                }}],
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2, 3]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 2, "kind": "+1/+1",
                "group": {"zone": "battlefield", "of": "you", "filter": {"subtype": "moogle"}}, "group_other": True,
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [4]},
        ),
    ]


register("Summon: Good King Mog XII", _summon_good_king_mog_xii)
