"""Zones and in-game card instances (RULE 400 zones, RULE 110 permanents).

Reference: docs/02_MVP_USECASES_REVISED.md R1.3 (Game State — Zones,
Stack, permanents), docs/07_GAME_LOOP_EFFECT_SYSTEM.md.

A `Card` (models/card.py) is the immutable *definition* of a card — its
printed characteristics. A `GameObject` is one *instance* of that card
inside a running game: a specific object in a specific zone with its own
mutable state (tapped, damage, counters, summoning sickness) and its own
identity, so two copies of the same card, or the same physical card seen
in two zones over time, stay distinguishable. This mirrors the rules'
distinction between a card and the object it becomes in play.
"""

from __future__ import annotations

import itertools
from enum import Enum
from typing import Any, Optional

from .card import Card


class Zone(str, Enum):
    """The zones a game object can occupy (RULE 400)."""

    LIBRARY = "library"
    HAND = "hand"
    BATTLEFIELD = "battlefield"
    GRAVEYARD = "graveyard"
    STACK = "stack"
    EXILE = "exile"
    COMMAND = "command"


#: Process-wide counter giving every GameObject a unique instance id.
_instance_counter = itertools.count(1)


def _combat_display_keywords(
    card: Card, granted: Optional[set[str]] = None
) -> list[str]:
    """Combat/evasion keyword labels for a card's board badges, including any
    granted by a layer-6 static ability (RULE 613.7f).

    Local (function-scoped) import of the pure `game.combat` recognition so
    the model layer gains no import-time dependency on `game/` (RULE-keyword
    recognition lives with the combat rules that consume it)."""
    from ..game.combat import display_keywords

    return display_keywords(card, granted)


class GameObject:
    """One instance of a card in a game, with its mutable in-play state."""

    def __init__(
        self,
        card: Card,
        owner_id: str,
        zone: Zone = Zone.LIBRARY,
        controller_id: Optional[str] = None,
        is_commander: bool = False,
    ) -> None:
        self.instance_id: int = next(_instance_counter)
        self.card = card
        self.owner_id = owner_id
        #: Who currently controls the object; defaults to its owner
        #: (RULE 108.4). Control can change but ownership can't.
        self.controller_id = controller_id or owner_id
        self.zone = zone
        #: Whether this object is a commander (RULE 903.6) — governs
        #: whether it returns to the command zone instead of the
        #: graveyard/etc. when it would otherwise leave play (RULE 903.9,
        #: see `RulesEngine._move_to_graveyard`/`counter_spell`).
        self.is_commander = is_commander

        # Permanent state (meaningful on the battlefield).
        self.tapped: bool = False
        #: Summoning sickness (RULE 302.6): a creature can't attack/tap
        #: until its controller has controlled it since their last turn
        #: began. Set when it enters, cleared at that controller's untap.
        self.summoning_sick: bool = True
        #: Damage marked this turn (RULE 120); cleared during cleanup.
        self.damage_marked: int = 0
        #: Counters on the permanent, keyed by kind (RULE 122): e.g.
        #: ``{"+1/+1": 2, "-1/-1": 1}``, ``{"loyalty": 3}``, ``{"charge": 1}``.
        #: +1/+1 and -1/-1 are tracked as *distinct* kinds (they don't merge
        #: on the object — they annihilate as a state-based action, RULE
        #: 704.5q, applied by the rules engine) so a "remove a +1/+1 counter"
        #: or "counts +1/+1 counters" effect stays correct. Power/toughness
        #: read the net (`plus_one_counters`).
        self.counters: dict[str, int] = {}

        #: Combat state (RULE 508). ``attacking`` marks a creature declared
        #: as an attacker this combat; ``combat_defender`` is *what* it is
        #: attacking — a serializable dict ``{"kind": "player", "id": ...}``
        #: or ``{"kind": "planeswalker", "instance_id": ...}``, or None for a
        #: "bare" swing with no legal defender (solo goldfish). Kept on the
        #: object (not the engine) so it survives a `GameState.clone()` for
        #: rewind. Cleared when the combat phase ends (RULE 511.3).
        self.attacking: bool = False
        self.combat_defender: Optional[dict[str, Any]] = None
        #: Blocking (RULE 509): ``blocking`` is the instance id of the
        #: attacker this creature is declared to block (None if not
        #: blocking); ``blocked_by`` lists the blocker instance ids assigned
        #: to this attacker. Both are cleared when combat ends (RULE 511.3).
        self.blocking: Optional[int] = None
        self.blocked_by: list[int] = []
        #: Set when this creature was dealt combat damage by a deathtouch
        #: source this combat (RULE 702.2b): any such creature is destroyed as
        #: a state-based action regardless of how little damage it took.
        #: Transient — cleared with the rest of combat state at end-of-combat.
        self.dealt_deathtouch_damage: bool = False

        #: The permanent this object is attached to (RULE 301.5 Equipment /
        #: RULE 303.4 Aura): the host's ``instance_id``, or None if not
        #: attached. Drives the "attached cards grouped around their host"
        #: display; set by the (future) equip/enchant resolution.
        self.attached_to: Optional[int] = None

        #: Effects this object contributes while in play, consulted by the
        #: rules engine (mtg_analyzer/game/). Typed loosely to avoid a
        #: model→game import; they hold `GameEffect` subclasses.
        self.triggered_abilities: list[Any] = []
        self.replacement_effects: list[Any] = []
        #: Static abilities (`StaticAbility`) this object grants through the
        #: layer system (RULE 613) — anthems, keyword grants, type changes,
        #: cost reductions. Read by `game/continuous.py`.
        self.static_effects: list[Any] = []
        self.activated_abilities: list[Any] = []
        #: Intrinsic keyword abilities bound off the card's own text (RULE 702),
        #: as catalogue slugs — the flag keywords the parser catalogue produced
        #: and the binder docked here (e.g. ``{"flying", "deathtouch"}``).
        #: Combat unions these with the card's recognized keywords; unlike
        #: `_granted_keywords` they are the object's *own* keywords, so they are
        #: not cleared by `reset_derived`.
        self.intrinsic_keywords: set[str] = set()

        #: Derived characteristics stamped by the continuous-effects layer
        #: engine (`game/continuous.py`, RULE 613). ``None`` / empty until a
        #: recompute runs, in which case they supersede the printed values;
        #: they fold in counters too, so an on-battlefield permanent reads its
        #: whole layer stack here. `reset_derived` clears them before a pass.
        self._derived_power: Optional[int] = None
        self._derived_toughness: Optional[int] = None
        self._granted_keywords: set[str] = set()
        self._added_types: set[str] = set()
        #: Per-object record of which static abilities changed it and how, in
        #: layer order — the data the UI's layer-trace view renders.
        self.static_trace: list[dict[str, Any]] = []

    def reset_derived(self) -> None:
        """Clear layer-engine output before a fresh `continuous.recompute`."""
        self._derived_power = None
        self._derived_toughness = None
        self._granted_keywords = set()
        self._added_types = set()
        self.static_trace = []

    # -- Delegated characteristics (read from the printed card) ---------

    @property
    def name(self) -> str:
        return self.card.name

    @property
    def is_creature(self) -> bool:
        # Printed creature, or made one by a layer-4 type-changing effect.
        return self.card.is_creature or "creature" in self._added_types

    @property
    def is_land(self) -> bool:
        return self.card.is_land

    @property
    def is_legendary(self) -> bool:
        return self.card.is_legendary

    @property
    def is_planeswalker(self) -> bool:
        return self.card.is_planeswalker

    @property
    def plus_one_counters(self) -> int:
        """Net +1/+1 counters (positive) vs. -1/-1 counters (negative).

        The single number power/toughness are shifted by (RULE 122.3): a
        creature with two +1/+1 and one -1/-1 counter reads +1 here. Kept as
        a read/write property over the typed `counters` dict so older code
        and fixtures that set a bare net still work.
        """
        return self.counters.get("+1/+1", 0) - self.counters.get("-1/-1", 0)

    @plus_one_counters.setter
    def plus_one_counters(self, value: int) -> None:
        self.counters.pop("+1/+1", None)
        self.counters.pop("-1/-1", None)
        if value > 0:
            self.counters["+1/+1"] = value
        elif value < 0:
            self.counters["-1/-1"] = -value

    def add_counters(self, kind: str, amount: int = 1) -> None:
        """Add (or, with a negative ``amount``, remove) counters of ``kind``.

        Counter totals never go below zero — removing more than are present
        drops the kind entirely (RULE 122.1c: a counter you can't remove
        simply isn't there).
        """
        total = self.counters.get(kind, 0) + amount
        if total > 0:
            self.counters[kind] = total
        else:
            self.counters.pop(kind, None)

    @property
    def power(self) -> Optional[int]:
        """Effective power (RULE 613 layer 7), or None for non-creatures.

        Prefers the value the continuous-effects engine stamped (which already
        folds in counters and any static modifiers); falls back to printed
        power plus counters when no layer pass has run (off-battlefield, unit
        tests). None only for something that is not a creature and has no
        layer-7 value (so an animated land still reports its P/T)."""
        if self._derived_power is not None:
            return self._derived_power
        if self.card.power is None:
            return None
        return self.card.power + self.plus_one_counters

    @property
    def toughness(self) -> Optional[int]:
        """Effective toughness (RULE 613 layer 7); see `power`."""
        if self._derived_toughness is not None:
            return self._derived_toughness
        if self.card.toughness is None:
            return None
        return self.card.toughness + self.plus_one_counters

    @property
    def granted_keywords(self) -> set[str]:
        """Keyword slugs granted by layer-6 static abilities (RULE 613.7f)."""
        return set(self._granted_keywords)

    # -- State transitions ----------------------------------------------

    def tap(self) -> None:
        self.tapped = True

    def untap(self) -> None:
        self.tapped = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the instance's game state (for the wire protocol)."""
        return {
            "instance_id": self.instance_id,
            "card_id": self.card.id,
            "name": self.card.name,
            "owner_id": self.owner_id,
            "controller_id": self.controller_id,
            "zone": self.zone.value,
            "tapped": self.tapped,
            "summoning_sick": self.summoning_sick,
            "damage_marked": self.damage_marked,
            "power": self.power,
            "toughness": self.toughness,
            # Card type info + combat/attachment state the board UI needs to
            # sort permanents into rows, group attachments, and show which
            # creature is attacking whom.
            "type_line": self.card.type_line,
            # `is_creature` honours a layer-4 type change (an animated land);
            # the rest read the printed card until those layers model them.
            "is_creature": self.is_creature,
            "is_land": self.card.is_land,
            "is_artifact": self.card.is_artifact,
            "is_enchantment": self.card.is_enchantment,
            "is_planeswalker": self.card.is_planeswalker,
            # Types added by a layer-4 effect (e.g. "creature"), for the board.
            "added_types": sorted(self._added_types),
            "attacking": self.attacking,
            "combat_defender": self.combat_defender,
            "blocking": self.blocking,
            "blocked_by": list(self.blocked_by),
            # Combat/evasion keyword labels the board shows as badges — the
            # same recognition the combat engine honours (printed keywords plus
            # any bound off the card by the parser and any granted by a layer-6
            # static ability), so display matches behaviour. Imported at call
            # time: `game.combat` is pure (no runtime model imports), so this
            # reads keywords without turning the model→game boundary into an
            # import cycle.
            "keywords": _combat_display_keywords(
                self.card, self._granted_keywords | self.intrinsic_keywords
            ),
            "counters": dict(self.counters),
            "attached_to": self.attached_to,
            # Layer-by-layer record of static effects that reshaped this object
            # (RULE 613), surfaced by the UI's optional static-effects panel.
            "static_trace": [dict(entry) for entry in self.static_trace],
        }

    def __repr__(self) -> str:
        return f"GameObject(#{self.instance_id} {self.card.name!r} in {self.zone.value})"
