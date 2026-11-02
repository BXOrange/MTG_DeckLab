"""RULE 608.2c / 701.20: "Reveal the top N cards of your library. For each card type among noncreature spells you've cast
this turn, you may put a card of that type from among the revealed cards into your hand. Put the rest on the bottom of your
library in a random order." (Hurkyl, Master Wizard.) The per-type decisions are `TypePicksRulesMixin`'s."""
from __future__ import annotations

from typing import Any, Optional

from .core import EffectRegistry, GameContext, GameEffect, _controller_of
from ...models.game.events import EventType

#: How many cards Hurkyl reveals ("the top five cards"): the printed number, named so the factory default has a why.
HURKYL_REVEAL_COUNT = 5


def noncreature_spell_types_cast_this_turn(context: GameContext, player_id: str) -> list[str]:
    """Every card type among the noncreature spells ``player_id`` has cast this turn, sorted (RULE 205.2a). Read from the
    turn's SPELL_CAST events, the same record `GameState.noncreature_spells_cast_this_turn` tallies."""
    from ..rules.misc_helpers import _CARD_TYPE_WORDS  # function-scoped: misc_helpers imports `continuous`

    types: set[str] = set()
    for event in context.state.events_this_turn():
        words = event.get("object_types") or []
        if event.type == EventType.SPELL_CAST and event.get("player_id") == player_id and "creature" not in words:
            types.update(word for word in words if word in _CARD_TYPE_WORDS)
    return sorted(types)


class RevealTopTypePicksEffect(GameEffect):
    def __init__(self, count: int = HURKYL_REVEAL_COUNT, source: Optional[Any] = None) -> None:
        super().__init__(source)
        self.count = max(1, int(count))

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        # The library's top is its last element; the revealed group is read top-first.
        revealed = list(reversed(player.library[-self.count:]))
        types = noncreature_spell_types_cast_this_turn(context, player.id)
        context.engine._open_type_pick(player, [obj.instance_id for obj in revealed], types, self.source)


EffectRegistry.register("reveal_top_type_picks", lambda p: RevealTopTypePicksEffect(
    count=int(p.get("count", HURKYL_REVEAL_COUNT) or HURKYL_REVEAL_COUNT)))
