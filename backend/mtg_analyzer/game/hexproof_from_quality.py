"""Scoped "hexproof from <quality>" checks for synthetic keywords (RULE 702.11d).

Plain hexproof is `combat.has_hexproof`; a quality-scoped hexproof is carried as a synthetic keyword the card's
own static grants (the `hexproof_from_own_colors` precedent) and evaluated against the targeting source here.
"""
from __future__ import annotations

from typing import Any, Optional

from ..models.game.game_object import Zone
from . import combat

#: Synthetic keyword for "hexproof from instants" (Elenda, Saint of Dusk).
HEXPROOF_FROM_INSTANTS = "hexproof_from_instants"


def blocked_by_scoped_hexproof(obj: Any, source: Optional[Any]) -> bool:
    """RULE 702.11d: ``obj`` can't be targeted by an opponent's ``source`` of the stated quality.

    An instant only ever acts as a spell on the stack (it has no battlefield abilities), so the source must be a
    stack object with the instant type.
    """
    if source is None or obj.controller_id == source.controller_id:
        return False
    if HEXPROOF_FROM_INSTANTS not in combat._obj_keywords(obj):
        return False
    return source.zone == Zone.STACK and "instant" in source.type_words
