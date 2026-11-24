"""MEC-169: "... then exile ~ and those creature cards" -- the cards a cost sacrificed, found again in the graveyard.

An activated ability's cost sacrificed the source and any number of creatures (Sword of the Ages). Each left the
battlefield as a new object (RULE 400.7), so the effect finds the card the cost put there by its recorded identity
(`GameObject.instance_id`) and the graveyard visit the sacrifice created (`cost_referents` ``graveyard_visit``): a card
that has since left the graveyard, or been replaced by another object, is no longer "that card" (RULE 608.2h) and is
skipped, while one the sacrifice never put there (a token, a card a replacement effect sent elsewhere) has no visit.
"""
from __future__ import annotations

from typing import Optional

from .core import GameEffect
from ...models.game.game_object import Zone


class ExileCostSacrificedEffect(GameEffect):
    """Exile the ``sacrificed`` cost referents that match: the creature cards, and/or the ability's own source."""

    def __init__(self, source=None, card_type: Optional[str] = "creature", include_source: bool = True):
        super().__init__(source)
        self.card_type = card_type
        self.include_source = include_source

    def apply(self, context, targets=None):
        if self.source is None:
            return
        records = (getattr(self.source, "cost_referents", None) or {}).get("sacrificed", [])
        for record in records:
            is_source = record["instance_id"] == self.source.instance_id
            if not ((self.include_source and is_source)
                    or (self.card_type == "creature" and record.get("creature_count"))):
                continue
            visit = record.get("graveyard_visit")
            card = context.state.find_object(record["instance_id"])
            if (visit is None or card is None or card.zone != Zone.GRAVEYARD
                    or card.zone_incarnation != visit):
                continue
            context.exile(card)
