from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_lord_of_pain() -> list[AbilitySpec]:
    """Menace
    Your opponents can't gain life.
    Whenever a player casts their first spell each turn, choose another target player. The Lord of Pain deals damage equal to that spell's mana value to the chosen player.

    — PLAY-ALL (Endless Punishment). Menace is a keyword; the life-gain lock and the "first spell each turn" head (``is_nth_spell_cast_this_turn``) are the parser's.
    The target is the new ``player_other_than_event_player`` kind (any living player except whoever cast the spell), the damage the spell's mana value off the
    firing event.
    """
    return [
        AbilitySpec("static", [EffectSpec("prevent_all_life_gain", {"scope": "opponents"})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount_from_trigger_event": "mana_value", "target_kind": "player_other_than_event_player"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group"}, "is_nth_spell_cast_this_turn": 1},
        ),
    ]


register("The Lord of Pain", _the_lord_of_pain)
