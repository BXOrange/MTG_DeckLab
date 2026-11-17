"""Counts of *players* satisfying a per-player predicate (PAR-284 milestone 17, RULE 102.2 / 608.2h).

"the number of opponents who control more lands than you", "for each opponent who was dealt damage this turn",
"your opponents with 4 or more cards in hand" are one amount family: a player scope plus one predicate over each
player in it. The parser reads them into ``{"players": <scope>, "where": <predicate>}`` and
`continuous.count_selector` hands that to `players_matching_count`, so a new phrase is a predicate row here and a
grammar row in `count_phrase.parse_players_matching`, never a named selector per card.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from ..models.game.events import EventType

if TYPE_CHECKING:  # pragma: no cover
    from ..models.game.game_state import GameState
    from ..models.game.player import Player

#: The player scopes a count may range over (RULE 102.2: an opponent is any other player; only living players count).
SCOPE_OPPONENTS = "opponents"
SCOPE_PLAYERS = "players"


def _scope_players(state: "GameState", controller_id: Optional[str], scope: str) -> "list[Player]":
    living = list(state.living_players())
    if scope == SCOPE_OPPONENTS:
        return [p for p in living if p.id != controller_id]
    return living if scope == SCOPE_PLAYERS else []


def _dealt_damage(state: "GameState", player: "Player", where: dict[str, Any], _controller_id: str) -> bool:
    """RULE 120.3: the player was dealt damage (by any source; ``combat`` restricts it to combat damage) this turn."""
    combat_only = bool(where.get("combat"))
    return any(
        event.type == EventType.DAMAGE and event.get("is_player") and event.get("target_id") == player.id
        and int(event.get("amount") or 0) > 0 and (event.get("combat") or not combat_only)
        for event in state.events_this_turn()
    )


def _hand_size(state: "GameState", player: "Player", where: dict[str, Any], _controller_id: str) -> bool:
    return len(player.hand) >= int(where["min"])


def _has_counters(state: "GameState", player: "Player", where: dict[str, Any], _controller_id: str) -> bool:
    """RULE 122.1: poison is its own attribute (RULE 704.5c), every other player counter lives in ``counters``."""
    kind = where["counter"]
    held = player.poison if kind == "poison" else int(player.counters.get(kind, 0))
    return held >= int(where["min"])


def _drew_this_turn(state: "GameState", player: "Player", where: dict[str, Any], _controller_id: str) -> bool:
    return state.cards_drawn_this_turn.get(player.id, 0) >= int(where["min"])


def _lands_entered_this_turn(state: "GameState", player: "Player", where: dict[str, Any], _controller_id: str) -> bool:
    return state.lands_entered_this_turn.get(player.id, 0) >= int(where["min"])


def _controls_compared(state: "GameState", player: "Player", where: dict[str, Any], controller_id: str) -> bool:
    """"controls more / fewer <objects> than you": the same structured selector read for the player and the controller."""
    from .continuous import count_selector  # function-scoped: continuous dispatches into this module

    theirs = count_selector(state, player.id, where["selector"])
    mine = count_selector(state, controller_id, where["selector"])
    return theirs > mine if where["compare"] == "more" else theirs < mine


#: Predicate kind -> reader. Each is checked per player in scope; the count is how many satisfy it.
_PREDICATES: dict[str, Callable[["GameState", "Player", dict[str, Any], str], bool]] = {
    "dealt_damage_this_turn": _dealt_damage,
    "hand_size": _hand_size,
    "counters": _has_counters,
    "drew_this_turn": _drew_this_turn,
    "lands_entered_this_turn": _lands_entered_this_turn,
    "controls_compared": _controls_compared,
}


def players_matching_count(state: "GameState", controller_id: Optional[str], spec: dict[str, Any]) -> int:
    """How many players in ``spec["players"]`` (relative to ``controller_id``) satisfy ``spec["where"]``."""
    predicate = _PREDICATES.get(spec.get("where", {}).get("kind", ""))
    if controller_id is None or predicate is None:
        return 0
    return sum(1 for p in _scope_players(state, controller_id, spec["players"])
               if predicate(state, p, spec["where"], controller_id))
