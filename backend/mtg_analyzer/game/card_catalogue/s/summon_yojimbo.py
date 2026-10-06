from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _summon_yojimbo() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after IV.)
    I — Exile target artifact, enchantment, or tapped creature an opponent controls.
    II, III — Until your next turn, creatures can't attack you unless their controller pays {2} for each of those creatures.
    IV — Create X Treasure tokens, where X is the number of opponents who control a creature with power 4 or greater.
    Vigilance

    — PLAY-ALL (Counter Blitz). Vigilance is the keyword. Chapter I is `exile` over the new ``artifact_enchantment_or_tapped_creature_you_dont_control`` target
    kind. II and III are a `grant_until` (``your_next_turn``, RULE 611.2b) of the `attack_tax` static on the Saga itself (``self_subject``). IV is a Treasure
    `create_token` counted by the new ``opponents_controlling_creature_power_4_or_greater`` selector.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "artifact_enchantment_or_tapped_creature_you_dont_control"})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "static": {"type": "attack_tax", "params": {"amount": 2}},
                "duration": "your_next_turn", "target_kind": None, "self_subject": True,
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2, 3]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Treasure", "count_selector": "opponents_controlling_creature_power_4_or_greater",
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [4]},
        ),
    ]


register("Summon: Yojimbo", _summon_yojimbo)
