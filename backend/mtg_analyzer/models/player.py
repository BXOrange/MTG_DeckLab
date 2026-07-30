"""Player state: life, mana pool, zones (RULE 102, RULE 103, RULE 400).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R1.3 (Player State — Life,
Mana Pool, Priority, "is Active Player?"), docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md.

A player owns the private/personal zones (library, hand, graveyard,
exile, command zone) plus the objects they control on the shared
battlefield. This model holds *state and primitive moves only* — drawing
mechanically takes cards off the library, but the replacement-effect and
triggered-ability consequences of a draw are the rules engine's job
(mtg_analyzer/game/), keeping the model layer free of rules logic so the
engine stays the single place rules live.
"""

from __future__ import annotations

import random
from typing import Any, Optional

from .emblem import Emblem
from .game_object import GameObject, Zone
from .mana_pool import ManaPool

#: Starting life for Commander/EDH (RULE 903.7).
DEFAULT_STARTING_LIFE = 40


class Player:
    """One player's game state and the zones they own."""

    #: Personal zones this player owns (the battlefield is shared and
    #: lives on GameState; command zone holds the commander).
    PERSONAL_ZONES = (Zone.LIBRARY, Zone.HAND, Zone.GRAVEYARD, Zone.EXILE, Zone.COMMAND)

    def __init__(
        self,
        id: str,
        name: str = "",
        life: int = DEFAULT_STARTING_LIFE,
        is_dummy: bool = False,
    ) -> None:
        self.id = id
        self.name = name or id
        self.life = life
        #: Poison counters (RULE 122.1, RULE 704.5c): a player with 10 or more
        #: loses the game as a state-based action. Tracked as a plain int so it
        #: deep-copies with the player for rewind and serializes to the UI.
        self.poison = 0
        #: Free-form named player counters (RULE 122): energy, experience, and
        #: any other "you have N X counters" resource. Kept generic (a slug →
        #: count map) so the Replay editor can set arbitrary ones without a
        #: model change per keyword.
        self.counters: dict[str, int] = {}
        self.mana_pool = ManaPool()
        #: A passive "goldfish" opponent (UC3): a real player for targeting,
        #: damage and stats, but one the turn loop never makes active and
        #: that takes no actions of its own. Lets a solo game have something
        #: to attack and to aim discard/draw/damage effects at.
        self.is_dummy = is_dummy

        #: Personal zones, each an ordered list of GameObjects. For the
        #: library, the *end* of the list is the top of the deck (draws
        #: pop from the end), so shuffling and dealing are cheap.
        self.zones: dict[Zone, list[GameObject]] = {zone: [] for zone in self.PERSONAL_ZONES}

        #: Per-turn flags, reset by the engine at the start of each turn.
        self.lands_played_this_turn = 0
        self.max_lands_per_turn = 1
        #: RULE 305.2: a one-turn "you may play an additional land this
        #: turn" grant (`ExtraLandPlayEffect`, Explore/Escape to the Wilds-
        #: shaped) — reset to 0 each turn (`GameEngine.begin_turn`) alongside
        #: `lands_played_this_turn`; `GameEngine.can_play_land` adds it to
        #: the per-turn cap on top of the standing `"extra_land_drop"` static
        #: grant (`game/continuous.py`'s `extra_land_plays_for`).
        self.extra_land_plays_this_turn = 0

        #: Whether this player has lost (RULE 104.3). Kept distinct from
        #: removal from the game so history/UI can show the reason.
        self.has_lost = False
        self.loss_reason: Optional[str] = None

        #: Combat damage taken from each commander this game (RULE 903.10a),
        #: keyed by the commander's instance id → ``{"name", "amount"}``. 21+
        #: from any single commander is a loss (a state-based action). Tracked
        #: per commander (not just a total) because the 21 threshold is
        #: per-commander, and shown in the UI next to life.
        self.commander_damage: dict[int, dict[str, Any]] = {}

        #: How many times each commander has been cast from the command zone
        #: this game (RULE 903.8), keyed by the commander's instance id. The
        #: commander tax adds {2} for each previous such cast; incremented on a
        #: command-zone cast and carried by rewind snapshots (a Player is
        #: deep-copied by `GameState.clone`).
        self.commander_casts: dict[int, int] = {}

        #: Effects that live on the player rather than a permanent —
        #: e.g. "skip your next untap step", "you can't lose the game".
        #: The rules engine reads these; see game/effects.py.
        self.player_effects: list[Any] = []

        #: Emblems this player owns and controls (RULE 114.2), created by
        #: `RulesEngine.create_emblem`. See `models/emblem.py`.
        self.emblems: list[Emblem] = []

        #: RULE 904.5: this player's face-down scheme deck, when they are the
        #: archenemy of an Archenemy game (empty for everyone else). Top of
        #: the deck is the **end** of the list, the same convention `library`
        #: uses.
        self.scheme_deck: list[GameObject] = []
        #: RULE 904.9: schemes that have been set in motion and stay face up
        #: — an *ongoing* scheme's abilities keep functioning until it's
        #: abandoned (904.11). A non-ongoing scheme never lands here: its one
        #: ability fires and the card goes straight back under the deck
        #: (904.10).
        self.ongoing_schemes: list[GameObject] = []
        #: RULE 902.2: this player's Vanguard avatar, face up in the command
        #: zone for the whole game with its abilities functioning from there
        #: (902.4). ``None`` outside a Vanguard game.
        self.vanguard: Optional[GameObject] = None
        #: RULE 902.3: the avatar's own maximum-hand-size modifier, applied
        #: once as the game starts and kept here so the cleanup step's
        #: discard-to-hand-size check can read it.
        self.hand_size_modifier: int = 0

        #: RULE 309.2b/309.3: the one dungeon card this player owns in the
        #: command zone, with their venture marker on it — ``None`` while
        #: they're not in a dungeon. A player can own only one at a time
        #: (309.3), which is why this is a single slot rather than a list;
        #: it's put here by `RulesEngine.venture_into_the_dungeon` and
        #: removed as the dungeon is completed (309.6/309.7).
        self.dungeon: Optional[Any] = None
        #: RULE 309.7: the names of the dungeons this player has completed
        #: this game, in order. Kept because "if you've completed a dungeon"
        #: / "whenever you complete a dungeon" are real card conditions, and
        #: because a completed dungeon leaves the game (309.6) so nothing
        #: else would remember it.
        self.completed_dungeons: list[str] = []

        #: RULE 701.51a "The Ring tempts you": how many times this player has
        #: been tempted, 0–4. The Ring emblem gains its four abilities one at
        #: a time in printed order, cumulatively, so the level *is* the
        #: emblem — no `Emblem` object is created for it, because unlike a
        #: RULE 114 emblem its abilities are fixed by the rules rather than
        #: quoted on a card, and they all read live state
        #: (`ring_bearer_id`). Applied by `RulesEngine.the_ring_tempts_you`,
        #: read by `RulesEngine._collect_inherent_triggers` (levels 2–4) and
        #: `game/continuous.py` (level 1).
        self.ring_level: int = 0
        #: RULE 701.52a: the `GameObject.instance_id` of this player's
        #: Ring-bearer, or ``None`` while they control no creature to be
        #: one. Re-chosen every time the Ring tempts them; cleared by the
        #: SBA sweep when that creature stops being a creature they control.
        self.ring_bearer_id: Optional[int] = None

        #: RULE 702.131c: "the city's blessing" — a onetime designation
        #: granted by Ascend (702.131a/b), unlike Monarch/Initiative not a
        #: single shared holder (`GameState.monarch_id`/`initiative_id`) but
        #: a plain per-player flag: "any number of players may have the
        #: city's blessing at the same time", and once granted it's kept
        #: "for the rest of the game" (never cleared). Set by
        #: `RulesEngine.get_city_blessing`.
        self.has_city_blessing: bool = False

    # -- Zone accessors --------------------------------------------------

    @property
    def library(self) -> list[GameObject]:
        return self.zones[Zone.LIBRARY]

    @property
    def hand(self) -> list[GameObject]:
        return self.zones[Zone.HAND]

    @property
    def graveyard(self) -> list[GameObject]:
        return self.zones[Zone.GRAVEYARD]

    @property
    def exile(self) -> list[GameObject]:
        return self.zones[Zone.EXILE]

    @property
    def command(self) -> list[GameObject]:
        return self.zones[Zone.COMMAND]

    # -- Primitive moves (no rules consequences; engine orchestrates) ----

    def add_to_zone(self, obj: GameObject, zone: Zone) -> None:
        """Place ``obj`` into one of this player's personal zones."""
        if zone not in self.zones:
            raise ValueError(f"{zone} is not a personal zone")
        obj.zone = zone
        self.zones[zone].append(obj)

    def remove_from_zone(self, obj: GameObject, zone: Zone) -> None:
        self.zones[zone].remove(obj)

    def shuffle_library(self) -> None:
        """Randomize the order of this player's library (RULE 701.20).

        A primitive move like `draw`: it changes zone contents but fires no
        event itself — the rules engine wraps this to announce a ``SHUFFLE``
        (so a "whenever a player shuffles" trigger can see it) and to keep
        library-searching (RULE 701.19e "then shuffle") in one place.
        """
        random.shuffle(self.library)

    def draw(self, count: int = 1) -> list[GameObject]:
        """Move up to ``count`` cards from the top of the library to hand.

        Returns the cards actually drawn. Drawing from an empty library
        does not itself lose the game here — that is a state-based action
        the rules engine checks (RULE 104.3c / 704.5c).
        """
        drawn: list[GameObject] = []
        for _ in range(count):
            if not self.library:
                break
            card = self.library.pop()  # top of deck
            card.zone = Zone.HAND
            self.hand.append(card)
            drawn.append(card)
        return drawn

    def add_commander_damage(self, commander_id: int, name: str, amount: int) -> None:
        """Record ``amount`` combat damage from a specific commander (RULE 903.10a)."""
        entry = self.commander_damage.setdefault(commander_id, {"name": name, "amount": 0})
        entry["amount"] += amount

    def add_counters(self, kind: str, amount: int = 1) -> None:
        """Mutate this player's counters (RULE 122): ``kind="poison"`` maps
        onto the dedicated `poison` attribute (RULE 704.5c's loss condition
        reads it directly); any other kind (energy/experience/…) is a
        generic `counters` entry — the player-level mirror of
        `GameObject.add_counters`'s "+1/+1" special-case.
        """
        if kind == "poison":
            self.poison = max(0, self.poison + amount)
            return
        total = self.counters.get(kind, 0) + amount
        if total > 0:
            self.counters[kind] = total
        else:
            self.counters.pop(kind, None)

    def lose_life(self, amount: int) -> None:
        self.life -= amount

    def gain_life(self, amount: int) -> None:
        self.life += amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "life": self.life,
            "poison": self.poison,
            "counters": dict(self.counters),
            "is_dummy": self.is_dummy,
            "mana_pool": self.mana_pool.to_dict(),
            "has_lost": self.has_lost,
            "loss_reason": self.loss_reason,
            "commander_damage": {str(k): v for k, v in self.commander_damage.items()},
            "emblems": [e.to_dict() for e in self.emblems],
            # RULE 309: the dungeon card in this player's command zone (with
            # their venture marker's current room), and every dungeon they
            # have completed this game (309.7).
            "dungeon": self.dungeon.to_dict() if self.dungeon is not None else None,
            "completed_dungeons": list(self.completed_dungeons),
            # RULE 902/904: the Vanguard avatar and the Archenemy scheme
            # state. The scheme deck ships as a count only — its cards are
            # face down (RULE 904.5), so their identity must not leave the
            # process any more than a library's does.
            "vanguard": self.vanguard.to_dict() if self.vanguard is not None else None,
            "scheme_deck_count": len(self.scheme_deck),
            "ongoing_schemes": [obj.to_dict() for obj in self.ongoing_schemes],
            # RULE 701.51/701.52: the Ring's level (0–4) and who carries it.
            "ring_level": self.ring_level,
            "ring_bearer_id": self.ring_bearer_id,
            # RULE 702.131c: the city's blessing designation (Ascend).
            "has_city_blessing": self.has_city_blessing,
            "library_count": len(self.library),
            "hand_count": len(self.hand),
            "hand": [obj.to_dict() for obj in self.hand],
            "graveyard": [obj.to_dict() for obj in self.graveyard],
            "exile": [obj.to_dict() for obj in self.exile],
            "command": [obj.to_dict() for obj in self.command],
            # Library contents (ordered, top of deck last) — the Replay
            # editor needs to see/edit the library. The goldfish UI ignores
            # this and uses `library_count` to keep the deck face-down.
            "library": [obj.to_dict() for obj in self.library],
        }

    def __repr__(self) -> str:
        return f"Player(id={self.id!r}, life={self.life}, hand={len(self.hand)}, library={len(self.library)})"
