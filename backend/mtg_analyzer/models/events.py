"""Game events — the currency of the effect system (RULE 603/614).

Reference: docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2/3 — events drive
triggered abilities and are what replacement effects rewrite).

An event is a *would-happen* description carried through the engine:
triggered abilities inspect events to decide whether they fire, and
replacement effects can rewrite an event (or cancel it) before it
actually resolves. Keeping events as plain typed data — a string ``type``
plus a ``data`` dict — is the parameter-based half of the hybrid design
in docs/07 PART 4: new event kinds need no new class.
"""

from __future__ import annotations

from typing import Any


class EventType:
    """Well-known event type names fired by the engine."""

    # Phase/step structure (RULE 500).
    PHASE_BEGIN = "PHASE_BEGIN"
    PHASE_END = "PHASE_END"
    STEP_BEGIN = "STEP_BEGIN"
    STEP_END = "STEP_END"
    TURN_BEGIN = "TURN_BEGIN"
    TURN_END = "TURN_END"
    UNTAP = "UNTAP"
    #: A permanent transitions untapped → tapped (RULE 701.21b) — fired once
    #: per genuine transition (not a no-op re-tap), and *not* for a permanent
    #: that enters the battlefield already tapped (RULE 614.1's tapped-entry
    #: conditions set `tapped` directly rather than going through this — a
    #: permanent entering tapped was never "not tapped" in the same turn, so
    #: it doesn't trigger a "becomes tapped" ability; see the real-card
    #: ruling for e.g. Kambal-style triggers, and Dionus, Elvish Archdruid's
    #: "whenever this creature becomes tapped").
    TAPPED = "TAPPED"

    # Object/zone movement.
    DRAW = "DRAW"
    DISCARD = "DISCARD"
    ENTERS_BATTLEFIELD = "ENTERS_BATTLEFIELD"
    LEAVES_BATTLEFIELD = "LEAVES_BATTLEFIELD"
    DIES = "DIES"
    MILL = "MILL"
    #: A player scried (RULE 701.18): looked at the top N of their library and
    #: reordered / bottomed them.
    SCRY = "SCRY"
    #: A card was moved to exile (RULE 406) — e.g. cascade/discover reveal.
    EXILE = "EXILE"
    #: A player searched their library (RULE 701.19) / shuffled it (RULE 701.20).
    LIBRARY_SEARCHED = "LIBRARY_SEARCHED"
    SHUFFLE = "SHUFFLE"

    # Spells/abilities. SPELL_CAST carries ``free=True`` when the spell was
    # cast without paying its mana cost (RULE 118.9 — cascade/discover/etc.),
    # so a "cast" trigger can distinguish a normal cast from a free one; a
    # spell put onto the battlefield instead (never cast) fires only
    # ENTERS_BATTLEFIELD, never SPELL_CAST.
    SPELL_CAST = "SPELL_CAST"
    SPELL_RESOLVED = "SPELL_RESOLVED"
    LAND_PLAYED = "LAND_PLAYED"

    # Combat / damage / life.
    DAMAGE = "DAMAGE"
    LIFE_GAINED = "LIFE_GAINED"
    LIFE_LOST = "LIFE_LOST"
    ATTACKS = "ATTACKS"
    BLOCKS = "BLOCKS"

    # Win/loss (RULE 104, RULE 704).
    PLAYER_WOULD_LOSE = "PLAYER_WOULD_LOSE"
    PLAYER_LOST = "PLAYER_LOST"


class GameEvent:
    """Something that is happening (or would happen) in the game."""

    def __init__(self, type: str, **data: Any) -> None:
        self.type = type
        self.data: dict[str, Any] = data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def copy_with(self, type: str | None = None, **overrides: Any) -> "GameEvent":
        """A copy with a possibly-different type and/or overridden data.

        Used by replacement effects, which produce a *new* event rather
        than mutating the original (RULE 614).
        """
        merged = {**self.data, **overrides}
        return GameEvent(type or self.type, **merged)

    def to_dict(self) -> dict[str, Any]:
        serializable = {
            k: v for k, v in self.data.items() if isinstance(v, (str, int, float, bool, type(None)))
        }
        return {"type": self.type, "data": serializable}

    def __repr__(self) -> str:
        return f"GameEvent({self.type!r}, {self.data!r})"
