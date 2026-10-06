from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _summon_kujata() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
    I — Lightning — This creature deals 3 damage to each of up to two target creatures.
    II — Ice — Up to three target creatures can't block this turn.
    III — Fire — Discard a card, then draw two cards. When you discard a card this way, this creature deals damage equal to that card's mana value to each opponent.
    Trample, haste

    — PLAY-ALL (Limit Break). Trample and haste are keywords. I is `damage` over up to two target creatures; II is `cant_block_this_turn` over up to three; III is Mog's ``mark_event_log`` window around `discard` +
    `draw` followed by the new `damage_opponents_by_discarded_mana_value` (the discarded card's mana value to each opponent). The damage is a separate reflexive trigger, queued only for an actual discard.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 3, "target_kind": "creature", "count": 2, "optional": True})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("cant_block_this_turn", {"target_kind": "creature", "count": 3, "optional": True})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("mark_event_log", {}),
                EffectSpec("discard", {"count": 1}),
                EffectSpec("draw", {"count": 2}),
                EffectSpec("damage_opponents_by_discarded_mana_value", {}),
            ],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [3]},
        ),
    ]


register("Summon: Kujata", _summon_kujata)
