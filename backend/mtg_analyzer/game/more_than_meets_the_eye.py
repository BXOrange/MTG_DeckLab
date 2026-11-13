"""More Than Meets the Eye (RULE 702.162): cast a transforming double-faced card converted.

"More Than Meets the Eye [cost]" means "You may cast this card converted by paying [cost] rather than its mana
cost" (RULE 702.162a), so it is an alternative cost (RULE 118.9) that also fixes the face the spell is cast with:
the back face is up on the stack (RULE 712.6b) and the permanent enters with it up.  The cast is its own
``face`` value, like the morph "face_down" cast, so every cast hook that already threads ``face`` carries it.
"""
from __future__ import annotations

from typing import Optional

from ..models.mana.mana_cost import ManaCost

#: The ``face`` value of a cast action / `can_cast` call that pays the More Than Meets the Eye cost.
CONVERTED_FACE = "converted"

#: Parametric keyword name the parser binds ``More Than Meets the Eye {cost}`` under.
KEYWORD = "more_than_meets_the_eye"

#: Attribute that carries the cost while the spell is mid-cast.  Switching to the back face rebinds the object's
#: keywords from the back face (which has no such keyword), so the front face's cost is stashed before the switch.
CAST_COST_ATTR = "_mtmte_cast_cost"


def cost_of(obj) -> Optional[ManaCost]:
    """``obj``'s More Than Meets the Eye cost, or ``None`` when it has none (or cannot be cast converted)."""
    raw = getattr(obj, CAST_COST_ATTR, None)
    if raw is None:
        params = (getattr(obj, "parametric_keywords", None) or {}).get(KEYWORD)
        raw = params.get("cost") if isinstance(params, dict) else None
    # RULE 712.7 / 702.162a: only a transforming double-faced card has a back face to be converted into.
    if not raw or not (obj.transformed or (obj.card.is_transforming and obj.card.back_face() is not None)):
        return None
    return ManaCost.parse(str(raw))
