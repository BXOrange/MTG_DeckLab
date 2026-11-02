"""'Choose any number of artifact tokens and/or creature tokens you control with different names. For each of them,
create a token that's a copy of it.' (Battle for Bretagard, chapter III).

"With different names" is a relation among the chosen set (RULE 601.2c-style group constraint, but a resolution-time
choice here, RULE 608.2d), so the pool offered is one representative per name: any subset of it is automatically
pairwise-distinct, and picking the representative of a name is equivalent to picking any token of that name. The picked
tokens become the next clause's ``previous_targets`` and a `copy_permanent` ``referent="previous_each"`` copies each
(RULE 707.2; `GameContext.copy_permanent`).
"""
from __future__ import annotations

from typing import Any, Optional

from .core import GameContext, GameEffect, _controller_of

#: What the pick is followed by: one token copy of each chosen token (RULE 111.1 / 707.2).
_COPY_EACH_CHOSEN = [{"type": "copy_permanent", "params": {"referent": "previous_each", "target_kind": None}}]


class ChooseDistinctlyNamedTokensToCopyEffect(GameEffect):
    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        representatives: dict[str, Any] = {}
        for obj in context.state.permanents_controlled_by(player.id):
            if obj.is_token and (obj.is_creature or obj.is_artifact):
                representatives.setdefault(obj.name, obj)
        if not representatives:
            return  # nothing to choose from: "any number" may be zero
        candidates = list(representatives.values())
        context.engine._request_choose_objects(
            player, candidates, "select_only", count=len(candidates), optional=True,
            prompt="Choose tokens with different names to copy", source=self.source, then_specs=_COPY_EACH_CHOSEN,
        )


EFFECT_FACTORIES = {
    "choose_distinctly_named_tokens_to_copy": lambda p: ChooseDistinctlyNamedTokensToCopyEffect(),
}
