"""Dungeon cards (RULE 309) as engine data: the printed room lines of a real
dungeon card → a `Dungeon` room graph, and each room's effect → live
`GameEffect`s.

A dungeon card's whole rules text is a list of rooms, one per line, in the
shape ``"<Room name> — <effect>. (Leads to: <room>, <room>)"``. The parenthetical
is *not* reminder text — it is the room graph's arrows (RULE 309.5a) — so the
graph is read off the **raw** printed text here, before `parser/oracle/
normalize.py` (which strips parentheticals) ever sees it. Only the effect half
is then normalized and run through the ordinary effect-body grammar
(`segmenter.parse_effect_body`), which means a room whose effect the parser
doesn't model yet simply has no effect rather than a wrong one — the usual
fail-closed rule. The room, its name and its arrows still work, so an
unmodeled room never breaks the dungeon's structure.

The pool a player chooses from (RULE 309.2a: "a dungeon card they own from
outside the game") is the committed catalogue in
`services/dungeon_database.py` — dungeons are never in a deck, so there is no
per-deck pool to derive one from.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..models.dungeon import Dungeon, DungeonRoom
from ..parser.oracle.normalize import normalize
from ..parser.oracle.segmenter import parse_effect_body
from ..services.dungeon_database import default_dungeon_database

#: One printed room line: "<name> — <effect> (Leads to: A, B)". The em dash is
#: what separates a room's name from its effect on every printed dungeon.
_ROOM_RE = re.compile(
    r"^(?P<name>[^—]+)—\s*(?P<effect>.*?)\s*(?:\(Leads to:\s*(?P<leads>[^)]*)\))?\s*$"
)

#: Undercity's own gate: "You can't enter this dungeon unless you 'venture
#: into Undercity.'" — a whole-card clause rather than a room, and the reason
#: RULE 701.49d's "venture into [quality]" variant exists at all.
_RESTRICTED_RE = re.compile(r"can't enter this dungeon unless", re.I)

#: RULE 726.2's dungeon: the initiative's inherent abilities venture into
#: *this* dungeon by name, never into a freely chosen one.
UNDERCITY = "Undercity"


def parse_dungeon_text(
    name: str, text: str, card_id: str = "", image_uri: str = ""
) -> Dungeon:
    """A dungeon card's printed text → its `Dungeon` room graph.

    Lines that don't parse as a room (Undercity's entry-restriction clause,
    a blank line) are skipped rather than becoming rooms — but the
    restriction itself is recorded, since it decides whether this dungeon can
    be chosen at all (RULE 309.2a vs. 701.49d).
    """
    rooms: list[DungeonRoom] = []
    restricted = False
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if _RESTRICTED_RE.search(line):
            restricted = True
            continue
        match = _ROOM_RE.match(line)
        if match is None:
            continue
        leads = [part.strip() for part in (match.group("leads") or "").split(",") if part.strip()]
        rooms.append(
            DungeonRoom(
                name=match.group("name").strip(),
                effect_text=match.group("effect").strip(),
                leads_to=leads,
            )
        )
    return Dungeon(
        name=name, rooms=rooms, card_id=card_id, image_uri=image_uri, restricted=restricted
    )


def _dungeon_from_entry(entry: dict[str, Any]) -> Dungeon:
    return parse_dungeon_text(
        entry.get("name") or "",
        entry.get("oracle_text") or "",
        card_id=entry.get("id") or "",
        image_uri=entry.get("image_uri_normal") or "",
    )


def all_dungeons() -> list[Dungeon]:
    """Every dungeon in the catalogue, as **fresh** objects — a `Dungeon`
    carries a player's own venture marker, so two players (or two games)
    must never share one instance."""
    return [_dungeon_from_entry(entry) for entry in default_dungeon_database().all_dungeons()]


def choosable_dungeons() -> list[Dungeon]:
    """RULE 309.2a's pool: every dungeon a plain "venture into the dungeon"
    may enter — i.e. all of them except one gated behind its own "venture
    into [quality]" wording (RULE 701.49d, Undercity)."""
    return [d for d in all_dungeons() if not d.restricted]


def dungeon_by_name(name: str) -> Optional[Dungeon]:
    """One named dungeon as a fresh object (RULE 701.49d's "venture into
    Undercity"), or ``None`` if the catalogue has no such card."""
    entry = default_dungeon_database().get(name)
    return _dungeon_from_entry(entry) if entry is not None else None


def room_effect_specs(room: DungeonRoom) -> list[dict[str, Any]]:
    """A room's printed effect → serialized `EffectSpec` dicts (RULE 309.4c).

    Empty when the effect grammar doesn't model the room's text — the room
    ability then triggers and resolves with no effect rather than guessing,
    the same fail-closed contract the oracle parser applies to a card.
    Serialized dicts (not built effects) so the result is cacheable and
    survives `GameState.clone()` untouched, exactly like the emblem
    ability specs `RulesEngine.create_emblem` binds from.
    """
    specs = parse_effect_body(normalize(room.effect_text))
    return [spec.to_dict() for spec in (specs or [])]
