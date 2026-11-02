"""Create token copies of the creature that was sacrificed to pay this ability's cost.

"{3}, {T}, Sacrifice another Zombie: Create two tokens that are copies of the sacrificed creature." (Cleaver
Skaab.) The cost's sacrifice stamps the victim's copiable `Card` on the ability's source
(`RulesEngine.note_sacrificed`, RULE 608.2h last-known information), so the copy survives a token victim that has
already ceased to exist (RULE 704.5d). Distinct from `copy_permanent`, whose referents are all live objects.
"""
from __future__ import annotations

from .core import EffectRegistry, GameEffect, _controller_of

#: How many copies Cleaver Skaab makes per activation.
_SKAAB_COPY_COUNT = 2


class CopySacrificedEffect(GameEffect):
    """RULE 707.2 / 111.5: ``count`` token copies of the creature sacrificed as this ability's cost."""

    def __init__(self, count: int = _SKAAB_COPY_COUNT, source=None):
        super().__init__(source)
        self.count = count

    def apply(self, context, targets=None):
        card = getattr(self.source, "sacrificed_cost_copiable_card", None)
        if card is None:
            return  # nothing was sacrificed (the cost was not paid this way): no copiable values to take
        controller = _controller_of(self.source, context)
        made = context.engine.create_token(controller.id, card, self.count)
        context.created_objects.extend(made)  # RULE 608.2: "those tokens" for any following clause


EffectRegistry.register("copy_sacrificed", lambda p: CopySacrificedEffect(int(p.get("count", _SKAAB_COPY_COUNT))))
