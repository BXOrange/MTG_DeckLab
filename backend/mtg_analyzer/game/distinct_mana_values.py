"""Count of *different mana values* among a set of cards ("for each different mana value among instant and sorcery
cards in your graveyard" -- Eris, Roar of the Storm). Kept out of `continuous.py` so the selector's logic has one home;
`continuous.count_selector` only dispatches here."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..models.game.game_state import GameState


def distinct_instant_sorcery_mana_values_in_graveyard(state: "GameState", controller_id: Optional[str]) -> int:
    """RULE 202.3: each card's mana value is read from its mana cost; two cards with the same value count once.
    Only ``controller_id``'s own graveyard is scanned ("your graveyard"); no controller matches nothing."""
    player = state.player_by_id(controller_id) if controller_id is not None else None
    if player is None:
        return 0
    values = set()
    for obj in player.graveyard:
        type_line = (obj.card.type_line or "").lower()
        if "instant" in type_line or "sorcery" in type_line:
            values.add(int(obj.card.converted_mana_cost or 0))
    return len(values)
