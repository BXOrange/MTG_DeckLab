"""'Exile target spell. It becomes plotted.' (Aven Interrupter) -- RULE 702.170 plotted designation.

A plotted card sits in exile; its owner may cast it without paying its mana cost, as a sorcery, on a later turn
(`RulesEngine`-side permission: `GameEngine._has_plot_permission`). The designation is the exile visit's, so it is
stamped on the exiled object together with the turn and zone incarnation (RULE 400.7).
"""
from __future__ import annotations

from typing import Any, Optional

from ...models.game.game_object import Zone
from ..targeting import TargetSpec
from .core import GameContext, GameEffect


class ExileTargetSpellAndPlotEffect(GameEffect):
    """Exile target spell (it is not countered: RULE 701.5 does not apply, so "can't be countered" is irrelevant),
    then it becomes plotted (RULE 702.170a: exiled face up, and only a spell card, not a copy or a token)."""

    def __init__(self, source: Optional[Any] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="spell")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None:
            return
        item = context.engine._stack_item_for(target)
        obj = getattr(item, "obj", None)
        if item is None or obj is None:
            return  # RULE 608.2b: the target spell is gone
        context.engine.counter_spell(target, exile_instead=True)
        if obj.zone != Zone.EXILE or obj.is_token:
            return  # a copy of a spell (a token-like stack object) ceases to exist instead of becoming plotted
        obj.plotted_card = True
        obj.plot_exiled_incarnation = obj.zone_incarnation
        obj.plot_exiled_turn = context.state.internal_turn.number


EFFECT_FACTORIES = {
    "exile_target_spell_and_plot": lambda p: ExileTargetSpellAndPlotEffect(),
}
