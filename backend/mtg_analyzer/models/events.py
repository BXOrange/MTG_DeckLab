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
    #: A permanent (``target_id``) would be destroyed (RULE 701.6) — fired
    #: pre-emptively by `RulesEngine.destroy` so a replacement effect can
    #: intercept it, chiefly a regeneration shield (RULE 701.16,
    #: `RulesEngine.regenerate`). Not fired by the *other* ways a permanent
    #: reaches the graveyard (0 toughness, sacrifice, discard, …) — RULE
    #: 701.16c/704.5f: those aren't "destruction" and regeneration can't
    #: replace them.
    DESTROY = "DESTROY"
    MILL = "MILL"
    #: A Saga (RULE 714) reached a new lore-counter count — carries
    #: ``instance_id`` (which Saga) and ``chapter`` (the new count), so a
    #: chapter ability's triggered condition can scope to both itself and
    #: the specific chapter number(s) it covers.
    #: One or more counters would be put on a permanent (RULE 122) — fired
    #: pre-emptively by `RulesEngine.add_counters` (only for counters being
    #: *placed*, never removed) so a "put twice that many instead" replacement
    #: (e.g. Doubling Season, RULE 616.1) can rewrite the ``amount`` before
    #: any counter actually lands.
    COUNTER = "COUNTER"
    #: One or more tokens would be created under a player's control (RULE
    #: 111.5) — fired pre-emptively by `RulesEngine.create_token` (battlefield
    #: entries only) so a "create twice that many instead" replacement (e.g.
    #: Doubling Season, Parallel Lives) can rewrite the ``amount`` before any
    #: token exists.
    CREATE_TOKENS = "CREATE_TOKENS"
    SAGA_CHAPTER = "SAGA_CHAPTER"
    #: A Class (RULE 716) reached a new class level — carries ``instance_id``
    #: and ``chapter`` (the new level), the same convention as SAGA_CHAPTER,
    #: so a rare "when this Class becomes level N" trigger can scope by both.
    CLASS_LEVEL = "CLASS_LEVEL"
    #: A player scried (RULE 701.18): looked at the top N of their library and
    #: reordered / bottomed them.
    SCRY = "SCRY"
    #: A player surveiled (RULE 701.31): looked at the top N of their library
    #: and put any number of them into their graveyard, the rest staying on
    #: top in any order (no bottoming option, unlike SCRY).
    SURVEIL = "SURVEIL"
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
    #: An attacker goes from unblocked to blocked (RULE 509.5) — fired once
    #: per attacker (never once per blocker), the moment its ``blocked_by``
    #: transitions from empty to non-empty within one `declare_blockers`
    #: call, carrying ``blocker_count`` (the final count) for keywords whose
    #: trigger amount scales with it (rampage). Distinct from `BLOCKS`, which
    #: fires per *blocker* and scopes to the blocker's own controller/type —
    #: afflict/bushido/rampage (RULE 702.130/702.45/702.23) all trigger off
    #: the *attacker* becoming blocked, which `BLOCKS` alone can't express.
    BECOMES_BLOCKED = "BECOMES_BLOCKED"
    #: RULE 702.112b: a creature just became renowned (its Renown N ability
    #: fired for the first, only time) — carries ``instance_id``, so a
    #: card's own separate "when this creature becomes renowned, …" trigger
    #: (Relic Seeker) can key off it distinctly from Renown's own counter-
    #: placing effect (`game/effects.py`'s `RenownEffect`, which fires this).
    RENOWNED = "RENOWNED"

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
