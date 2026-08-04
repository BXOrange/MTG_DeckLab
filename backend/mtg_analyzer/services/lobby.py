"""The multiplayer lobby: who is connected, and which games are forming (UC4).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md UC4,
docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md.

This module is deliberately **rules-free**: it knows about people and
tables, not about Magic. It answers two questions —

* *Who is here?* Every connected client is a `LobbyPlayer` in one of three
  presence states: ``online`` (connected, but off in some other tab),
  ``available`` (sitting in the lobby, not in a game) and ``playing`` (in
  a game, as a seat or an observer). Presence is driven by the client's
  own `/ws/lobby` connection (`api/multiplayer_ws.py`): connecting makes
  you ``online``, opening the Multiplayer tab reports ``available``, and
  joining a game flips you to ``playing``.

  A player is identified by their **name** (the Profil tab's free text —
  this app has no auth). That's a deliberate trade: it means a reload or a
  dropped connection walks straight back into the same seat, and it means
  two people sharing a name share a seat. Losing the socket doesn't drop a
  seated player — it starts a grace period
  (`config.MULTIPLAYER_DISCONNECT_GRACE_SECONDS`, `disconnect`/`sweep`) in
  which they can come back; a player with no seat is dropped at once,
  since there's nothing to hold for them.

* *What can I join?* A `LobbyGame` is a table in one of three statuses:
  ``setup`` (seats being filled and configured), ``running`` (a real
  `GameSession` exists behind it) and ``finished``.

A seat also carries the one purely decorative thing this module knows
about: its **banner colour** (`Seat.banner_color`, `normalize_banner_color`
— any subset of WUBRG, or grey for colourless), which is what the shared
board paints that player's title bar in. It lives here rather than in the
game because it is a property of the person at the table, not of the game
state, and because it has to be visible to everyone in Setup before there
is a game at all.

A seat can also be filled by a **bot** (`add_bot`, `Seat.bot_kind` —
`services/bots.py` for what a bot actually does). From here a bot is just
a `LobbyPlayer` that happens to have no socket: it is exempt from both
watchdogs, it doesn't appear in the "who is connected" list, the host
picks its deck for it, and it accepts the table automatically because it
has no opinion to withhold. The *kind* stays an opaque string in this
module — it stores which bot without knowing what one is.

Handing the game off to the rules engine is the one thing this module
does *not* do itself: `start()` takes an already-built `GameSession` id
from the caller (`api/multiplayer.py`, which owns deck resolution), so
the lobby never imports the engine or the card loader.

Everything is in-memory and single-process, like `GameSessionManager` and
`game_ws.py`'s connection registry — restarting the server empties the
lobby.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from mtg_analyzer.config import (
    MULTIPLAYER_DISCONNECT_GRACE_SECONDS,
    MULTIPLAYER_IDLE_TIMEOUT_SECONDS,
)


def normalize_name(name: str) -> str:
    """The key a player name is recognized by across reconnects.

    Case- and whitespace-insensitive, because the name is retyped by a
    human in the Profil tab and "Bernd " coming back as "bernd" should
    still find their seat.
    """
    return " ".join((name or "").split()).casefold()

#: The five colours a banner can be flown in, in canonical WUBRG order —
#: a `Seat.banner_color` is any *subset* of them (31 combinations, enough to
#: fly a deck's whole colour identity) or `COLORLESS_BANNER` for none.
#: Deliberately just letters here: this module doesn't know what a colour
#: looks like, only that a seat has picked one of a fixed vocabulary — the
#: actual palette is the frontend's (`frontend/src/js/bannerColors.js`).
BANNER_COLOR_LETTERS = "wubrg"
#: The grey banner: no colour, i.e. a colourless deck.
COLORLESS_BANNER = "c"


def normalize_banner_color(value: Optional[str]) -> Optional[str]:
    """Canonicalize a banner-colour key; ``None`` means "not chosen yet".

    Free client input ("WU", "uw", "Gr") is reduced to the same key, so the
    same pair of colours is always stored the same way: the WUBRG-ordered
    letters, or `COLORLESS_BANNER` when nothing recognizable is left. It's
    a normalizer rather than a validator on purpose — same treatment as
    `normalize_name` — since an unknown letter here is a cosmetic typo, not
    something worth failing a request over.
    """
    if value is None:
        return None
    letters = {ch for ch in str(value).lower() if ch in BANNER_COLOR_LETTERS}
    if not letters:
        return COLORLESS_BANNER
    return "".join(ch for ch in BANNER_COLOR_LETTERS if ch in letters)


#: Presence states, in increasing order of "busy".
ONLINE = "online"
AVAILABLE = "available"
PLAYING = "playing"

#: Game statuses.
SETUP = "setup"
RUNNING = "running"
FINISHED = "finished"

#: Biggest table the lobby will open. Four is the Commander pod size, and
#: also where the board UI stops being readable — the engine itself has no
#: opinion (`GameState.next_active_index` rotates through any number of
#: players, `GameEngine.legal_defenders_for` offers every opponent, and the
#: RULE 800.4a deferred-leave sweep is written for N), so this is a UI cap
#: rather than a rules one. Two stays the default (`LobbyGame.num_players`).
MAX_SEATS = 4
#: Smallest table: a shared game needs somebody to share it with.
MIN_SEATS = 2
#: Upper bound on `LobbyGame.takebacks_per_player` — purely a sanity clamp
#: (nothing rules-based caps it), so a typo in the input can't hand out an
#: effectively unlimited undo budget.
MAX_TAKEBACKS_PER_PLAYER = 20


class LobbyError(Exception):
    """A lobby operation was invalid (unknown game, seat taken, …)."""


@dataclass
class LobbyPlayer:
    """One client. **The player name is the identity** (`normalize_name`).

    The name comes from the Profil tab and is not authenticated — this app
    has no accounts — but it is the only handle that survives a page
    reload, so it is what a returning client is recognized by: reconnecting
    with the same name walks back into the same seat, with the game exactly
    as it was left (`Lobby.connect`). The trade-off is deliberate and worth
    stating plainly: two people who pick the same name *are* the same
    player here, and the second one to connect takes the seat over. Give
    everyone at the table a distinct name.

    ``id`` stays a stable opaque handle (every REST call takes it, and it
    doubles as the `Player.id` inside the `GameState`, so a seat and its
    player are the same thing by construction) — it just isn't what
    identifies a returning client any more.

    ``connected`` is whether a live `/ws/lobby` socket is attached.
    A disconnected player keeps their seat until ``disconnect_deadline``
    passes (`config.MULTIPLAYER_DISCONNECT_GRACE_SECONDS`); meanwhile the
    server passes priority for them so the table isn't stuck waiting.
    """

    id: str
    name: str
    state: str = ONLINE
    game_id: Optional[str] = None
    connected: bool = True
    #: Monotonic deadline after which the seat is given up; None while connected.
    disconnect_deadline: Optional[float] = None
    #: Monotonic timestamp of this player's last action in a game — what
    #: `config.MULTIPLAYER_IDLE_TIMEOUT_SECONDS` is measured against.
    last_action_at: float = field(default_factory=time.monotonic)
    #: A bot (`services/bots.py`) rather than a client. It exists here at
    #: all because everything downstream — `pass_for_absent_players`, the
    #: idle sweep, `game_for_player` — asks the lobby "is this seat's
    #: player still with us?", and a bot must answer yes. It has no socket,
    #: so it is exempt from both watchdogs and stays out of the "who is
    #: connected" list (`players`); it lives and dies with its seat.
    is_bot: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "game_id": self.game_id,
            "connected": self.connected,
            "is_bot": self.is_bot,
        }


@dataclass
class Seat:
    """One player's slot at a table during setup.

    ``ready`` is the "accept" of "when all players accept, the game
    starts" — it's cleared again whenever anything about the table changes
    (someone joins or leaves, a deck or the mulligan style changes), so
    nobody can be carried into a game they didn't agree to.

    ``bot_kind`` marks the seat as held by a bot (`services/bots.py`'s
    `Bot.kind`) rather than a person. It stays an opaque string here —
    this module is rules-free and doesn't know what a bot *does*; the API
    layer validates it against the registry. A bot never accepts anything,
    so `is_ready` treats a bot seat with a deck as accepted: a bot has no
    opinion about the table to withhold.

    ``banner_color`` is purely cosmetic (`normalize_banner_color`): the
    colours this seat's board banner is painted in on everyone's screen.
    ``None`` means the player hasn't picked one and hasn't got one from
    their deck's colour identity either, which the board draws as the plain
    felt header it always had.
    """

    player_id: str
    name: str
    deck_id: Optional[str] = None
    deck_name: str = ""
    ready: bool = False
    bot_kind: Optional[str] = None
    banner_color: Optional[str] = None

    @property
    def is_bot(self) -> bool:
        return bool(self.bot_kind)

    @property
    def is_ready(self) -> bool:
        return bool(self.deck_id) if self.is_bot else self.ready

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "deck_id": self.deck_id,
            "deck_name": self.deck_name,
            "ready": self.is_ready,
            "bot_kind": self.bot_kind,
            "is_bot": self.is_bot,
            "banner_color": self.banner_color,
        }


@dataclass
class LobbyGame:
    """A table: forming (``setup``), live (``running``) or over (``finished``)."""

    id: str
    name: str
    host_id: str
    num_players: int = 2
    mulligan_style: str = "london"
    #: How many times each seat may take back its own last move over the
    #: whole game (UC4 Setup) — a table-wide, rules-free convenience, not a
    #: RULE 104 concept. 0 (the default) means the feature is off; the
    #: budget is per seat, not shared. `services/game_session.py`'s
    #: `GameSession.take_back` enforces it once the game is running.
    takebacks_per_player: int = 0
    #: RULE 103.1/103.2 — how the table settles seating and who begins.
    #: Both default off, which keeps the historical behaviour: seats are in
    #: join order (the host sat down first, so the host starts). The lobby
    #: only *records* the choice; `seating_order()` below is what applies
    #: it, once, when the game is built.
    randomize_seating: bool = False
    random_starting_player: bool = False
    #: PLR-13: a `models/game_format.py` name — an opaque string here (this
    #: module is rules-free, same treatment as `mulligan_style`); the API
    #: layer validates it against `FORMATS` before it ever reaches here.
    game_format: str = "commander"
    #: RULE 904: which seat is the Archenemy when `game_format` has that
    #: variant — a player id, or None for "the host" (`api/multiplayer.py`'s
    #: `start_game` resolves that default, since this module doesn't know
    #: which seat is the host beyond `host_id` itself).
    archenemy_id: Optional[str] = None
    status: str = SETUP
    seats: list[Seat] = field(default_factory=list)
    #: Watchers (RULE-irrelevant): they see the public board and no hands.
    observer_ids: list[str] = field(default_factory=list)
    #: The `GameSession` id once `start()` has been called.
    session_id: Optional[str] = None
    #: Player ids that conceded, in order — kept here as well as in the
    #: game state so the lobby listing can say "2 von 3 noch dabei"
    #: without loading the session.
    conceded_ids: list[str] = field(default_factory=list)

    @property
    def is_full(self) -> bool:
        return len(self.seats) >= self.num_players

    @property
    def all_ready(self) -> bool:
        return self.is_full and all(seat.is_ready for seat in self.seats)

    @property
    def has_human_seat(self) -> bool:
        """Whether anybody at this table is a person (`Seat.is_bot`)."""
        return any(not seat.is_bot for seat in self.seats)

    def seat_for(self, player_id: str) -> Optional[Seat]:
        return next((s for s in self.seats if s.player_id == player_id), None)

    def seating_order(self, rng: Optional[random.Random] = None) -> list[Seat]:
        """The seats in the order the game should be built in — turn order.

        RULE 103.1 (seating) and RULE 103.2 (who goes first) are decisions a
        real table makes before the game; here they're two independent
        table settings, applied in that same order:

        * ``randomize_seating`` shuffles who sits next to whom, i.e. the
          order turns rotate in.
        * ``random_starting_player`` rotates that ring so a random seat
          begins. A rotation rather than a swap on purpose — seating is
          *whose left you sit on*, and picking a different starting point
          must not disturb it.

        Both off (the default) returns the seats in join order, which is
        what this table did before either option existed: the host sat down
        first and therefore starts.

        Deliberately a pure function of the seats plus an injectable ``rng``
        rather than something that mutates ``self.seats``: it's called once,
        when the game starts, and a test needs to be able to pin the roll.
        """
        order = list(self.seats)
        roll = rng or random
        if self.randomize_seating:
            roll.shuffle(order)
        if self.random_starting_player and len(order) > 1:
            start = roll.randrange(len(order))
            order = order[start:] + order[:start]
        return order

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "host_id": self.host_id,
            "num_players": self.num_players,
            "mulligan_style": self.mulligan_style,
            "takebacks_per_player": self.takebacks_per_player,
            "randomize_seating": self.randomize_seating,
            "random_starting_player": self.random_starting_player,
            "game_format": self.game_format,
            "archenemy_id": self.archenemy_id,
            "status": self.status,
            "seats": [s.to_dict() for s in self.seats],
            "observer_ids": list(self.observer_ids),
            "session_id": self.session_id,
            "conceded_ids": list(self.conceded_ids),
            "all_ready": self.all_ready,
        }


class Lobby:
    """In-memory registry of connected players and forming/running games."""

    def __init__(self) -> None:
        self._players: dict[str, LobbyPlayer] = {}
        #: Normalized name → player, the index a reconnect is resolved through.
        self._by_name: dict[str, LobbyPlayer] = {}
        self._games: dict[str, LobbyGame] = {}

    # -- Presence ------------------------------------------------------

    def connect(self, name: str, player_id: Optional[str] = None) -> LobbyPlayer:
        """Register a client, **reclaiming their seat if the name is known**.

        Identity is the player name (see `LobbyPlayer`): a client that
        reloads the page, loses its connection, or is dropped by the idle
        sweeper comes back with the same name from the Profil tab and lands
        back in the same seat, mid-game. ``player_id`` is honoured when the
        client still has one (it saves a lookup and survives a rename), but
        it is no longer *required* for a reclaim — that's the whole point.

        A name that is already connected is taken over rather than
        rejected: the common case by far is the old socket being dead
        without the server having noticed yet, and refusing there would
        lock a player out of their own game. `api/multiplayer_ws.py` closes
        the previous socket when this happens.
        """
        existing = None
        if player_id:
            existing = self._players.get(player_id)
        if existing is None:
            existing = self._by_name.get(normalize_name(name))
        if existing is not None:
            if name:
                self._rename(existing, name)
            existing.connected = True
            existing.disconnect_deadline = None
            existing.last_action_at = time.monotonic()
            return existing

        player = LobbyPlayer(id=player_id or str(uuid.uuid4()), name=" ".join(name.split()) or "Spieler")
        self._players[player.id] = player
        self._by_name[normalize_name(player.name)] = player
        return player

    def _rename(self, player: LobbyPlayer, name: str) -> None:
        display = " ".join(name.split())  # trimmed, but the typed case is kept
        if normalize_name(player.name) != normalize_name(display):
            self._by_name.pop(normalize_name(player.name), None)
            self._by_name[normalize_name(display)] = player
        player.name = display
        for game in self._games.values():
            seat = game.seat_for(player.id)
            if seat is not None:
                seat.name = display

    def disconnect(self, player_id: str) -> LobbyPlayer | None:
        """A client's socket went away: hold their seat, don't drop them.

        They stay in the lobby as ``connected=False`` until
        `MULTIPLAYER_DISCONNECT_GRACE_SECONDS` passes (`sweep`), so a reload
        or a flaky connection doesn't cost anyone their game. A player who
        wasn't at a table has nothing to hold and is removed immediately —
        keeping them would just show a ghost in everyone's player list.
        """
        player = self._players.get(player_id)
        if player is None:
            return None
        player.connected = False
        if not player.game_id:
            self._remove_player(player)
            return player
        if MULTIPLAYER_DISCONNECT_GRACE_SECONDS <= 0:
            player.disconnect_deadline = None  # held indefinitely
        else:
            player.disconnect_deadline = time.monotonic() + MULTIPLAYER_DISCONNECT_GRACE_SECONDS
        return player

    def _remove_player(self, player: LobbyPlayer) -> None:
        """Drop a player for good and tidy up whatever they were sitting at."""
        self._players.pop(player.id, None)
        if self._by_name.get(normalize_name(player.name)) is player:
            self._by_name.pop(normalize_name(player.name), None)
        game_id = player.game_id
        if not game_id:
            return
        try:
            self.leave(game_id, player.id)
        except LobbyError:
            return
        # A running game keeps its seats when someone leaves (the position
        # is still the table's), but once *nobody* who belongs to it is
        # connected any more there's no one left to come back to it — drop
        # it rather than leaving a dead table in everyone's list forever.
        # Bots don't count as someone coming back: they have no client, so
        # a table of nothing but bots would otherwise play on forever with
        # no one watching.
        game = self._games.get(game_id)
        if game is None:
            return
        involved = [s.player_id for s in game.seats if not s.is_bot] + list(game.observer_ids)
        if not any(pid in self._players for pid in involved):
            self._drop_game(game)

    def _drop_game(self, game: LobbyGame) -> None:
        """Remove a table and every bot that only existed to sit at it."""
        for seat in game.seats:
            if seat.is_bot:
                self._players.pop(seat.player_id, None)
        self._games.pop(game.id, None)

    def touch(self, player_id: str) -> None:
        """Record that ``player_id`` just acted (resets their idle timer)."""
        player = self._players.get(player_id)
        if player is not None:
            player.last_action_at = time.monotonic()

    def idle_players(self, game: LobbyGame) -> list[LobbyPlayer]:
        """Seated players who have been silent past the idle timeout.

        Only meaningful for whoever the game is actually waiting on — the
        caller checks that (it needs the `GameSession` to know who holds
        priority, and this module deliberately knows nothing about Magic).
        """
        if MULTIPLAYER_IDLE_TIMEOUT_SECONDS <= 0:
            return []
        cutoff = time.monotonic() - MULTIPLAYER_IDLE_TIMEOUT_SECONDS
        return [
            player
            for seat in game.seats
            if (player := self._players.get(seat.player_id)) is not None
            and not player.is_bot  # no socket to time out, and never silent
            and player.connected
            and player.last_action_at <= cutoff
        ]

    def expired_players(self) -> list[LobbyPlayer]:
        """Disconnected players whose grace period has run out."""
        now = time.monotonic()
        return [
            p
            for p in self._players.values()
            if not p.connected and p.disconnect_deadline is not None and p.disconnect_deadline <= now
        ]

    def forget(self, player_id: str) -> None:
        """Remove a player for good (their grace period lapsed)."""
        player = self._players.get(player_id)
        if player is not None:
            self._remove_player(player)

    def set_presence(self, player_id: str, state: str) -> LobbyPlayer:
        """Report where a client is (``online``/``available``).

        ``playing`` is never set from outside — it's derived from actually
        being in a game, so a client can't claim to be playing while it
        isn't (or, more usefully, can't accidentally show as available
        while it holds a seat).
        """
        player = self.player(player_id)
        if player.game_id:
            player.state = PLAYING
        elif state in (ONLINE, AVAILABLE):
            player.state = state
        return player

    def player(self, player_id: str) -> LobbyPlayer:
        player = self._players.get(player_id)
        if player is None:
            raise LobbyError(f'unknown player "{player_id}"')
        return player

    def find(self, player_id: str) -> Optional[LobbyPlayer]:
        """`player`, but ``None`` instead of raising — for sweeps and probes."""
        return self._players.get(player_id)

    def players(self) -> list[LobbyPlayer]:
        """Everyone *connected* — the Setup screen's player list.

        Bots are deliberately not in it: this list answers "who else is on
        the server", and a bot isn't. It shows up where it actually is,
        as a seat at its own table.
        """
        return sorted(
            (p for p in self._players.values() if not p.is_bot), key=lambda p: p.name.lower()
        )

    # -- Games ---------------------------------------------------------

    def game(self, game_id: str) -> LobbyGame:
        game = self._games.get(game_id)
        if game is None:
            raise LobbyError(f'unknown game "{game_id}"')
        return game

    def games(self) -> list[LobbyGame]:
        return list(self._games.values())

    def game_for_player(self, player_id: str) -> Optional[LobbyGame]:
        game_id = self.player(player_id).game_id
        return self._games.get(game_id) if game_id else None

    def create(self, player_id: str, name: str = "", num_players: int = 2) -> LobbyGame:
        """Open a new table and seat its creator (the host) at it."""
        player = self.player(player_id)
        if player.game_id:
            raise LobbyError("you are already in a game — leave it first")
        seats = max(MIN_SEATS, min(int(num_players or MIN_SEATS), MAX_SEATS))
        game = LobbyGame(
            id=str(uuid.uuid4()),
            name=(name or f"Spiel von {player.name}").strip(),
            host_id=player_id,
            num_players=seats,
        )
        self._games[game.id] = game
        self._join(game, player)
        return game

    def join(self, game_id: str, player_id: str) -> LobbyGame:
        game = self.game(game_id)
        player = self.player(player_id)
        if game.status != SETUP:
            raise LobbyError("this game has already started — you can only watch it")
        if player.game_id and player.game_id != game_id:
            raise LobbyError("you are already in a game — leave it first")
        if game.seat_for(player_id) is None and game.is_full:
            raise LobbyError("this game is full")
        self._join(game, player)
        return game

    def _join(self, game: LobbyGame, player: LobbyPlayer) -> None:
        if game.seat_for(player.id) is None:
            game.seats.append(Seat(player_id=player.id, name=player.name))
        player.game_id = game.id
        player.state = PLAYING
        # The table changed shape, so every earlier "I accept" is stale.
        self._unready(game)

    def add_bot(self, game_id: str, requester_id: str, kind: str, name: str = "") -> LobbyGame:
        """Seat a bot at ``game_id`` (host only). ``kind`` is opaque here.

        The bot gets a `LobbyPlayer` like anyone else, because a seat's
        player has to be findable for the rest of the machinery to work —
        but it never enters the name index (`_by_name`), since a bot has
        no client to reclaim it and two tables may perfectly well each want
        a "Gieriger Bot".
        """
        game = self._setup_game(game_id)
        if game.host_id != requester_id:
            raise LobbyError("only the host can add a bot")
        if game.is_full:
            raise LobbyError("this game is full")
        bot = LobbyPlayer(
            id=f"bot:{uuid.uuid4()}",
            name=" ".join((name or "Bot").split()),
            state=PLAYING,
            game_id=game.id,
            is_bot=True,
        )
        self._players[bot.id] = bot
        game.seats.append(Seat(player_id=bot.id, name=bot.name, bot_kind=kind))
        self._unready(game)
        return game

    def remove_bot(self, game_id: str, requester_id: str, bot_id: str) -> LobbyGame:
        """Take a bot back off the table (host only)."""
        game = self._setup_game(game_id)
        if game.host_id != requester_id:
            raise LobbyError("only the host can remove a bot")
        seat = game.seat_for(bot_id)
        if seat is None or not seat.is_bot:
            raise LobbyError("that seat is not a bot")
        game.seats = [s for s in game.seats if s.player_id != bot_id]
        self._players.pop(bot_id, None)
        self._unready(game)
        return game

    def observe(self, game_id: str, player_id: str) -> LobbyGame:
        """Watch a game instead of playing it (no hand, no actions)."""
        game = self.game(game_id)
        player = self.player(player_id)
        if player.game_id and player.game_id != game_id:
            raise LobbyError("you are already in a game — leave it first")
        if game.seat_for(player_id) is not None:
            raise LobbyError("you have a seat in this game — leave it before watching")
        if player_id not in game.observer_ids:
            game.observer_ids.append(player_id)
        player.game_id = game.id
        player.state = PLAYING
        return game

    def leave(self, game_id: str, player_id: str) -> Optional[LobbyGame]:
        """Leave a table. Returns the game, or None once it's been dropped.

        An empty table is dropped rather than left lying around; a running
        game keeps its (conceded) seat, since the position and the
        end-of-match review still belong to everyone at the table.
        """
        game = self.game(game_id)
        player = self._players.get(player_id)
        if player is not None and player.game_id == game_id:
            player.game_id = None
            player.state = AVAILABLE
        if player_id in game.observer_ids:
            game.observer_ids.remove(player_id)
            return game
        # A *finished* table is left the same way a forming one is: the game
        # is over, so there is no position left to preserve for anyone, and
        # a played-out table that lingers in every player's lobby list is
        # just litter. Only a game still RUNNING keeps the seat of someone
        # who walks away (they may yet come back to it).
        if game.status in (SETUP, FINISHED):
            game.seats = [s for s in game.seats if s.player_id != player_id]
            self._unready(game)
            # A table nobody is sitting at is gone — and a table with only
            # bots left at it is nobody's, since a bot can't invite anyone
            # or start the game.
            if not game.has_human_seat:
                self._drop_game(game)
                return None
            if game.host_id == player_id:
                game.host_id = next(s.player_id for s in game.seats if not s.is_bot)
        return game

    def set_deck(
        self,
        game_id: str,
        player_id: str,
        deck_id: str,
        deck_name: str = "",
        seat_id: Optional[str] = None,
    ) -> LobbyGame:
        """Pick a seat's deck. ``seat_id`` names a *bot* seat the host picks for.

        A bot can't choose its own deck, so somebody has to — the host,
        and only for a bot seat. Everyone else picks for themselves, which
        is what the default (``seat_id is None``) means.
        """
        game = self._setup_game(game_id)
        seat = self._seat_to_configure(game, player_id, seat_id)
        seat.deck_id = deck_id or None
        seat.deck_name = deck_name
        # The table changed, so *everyone's* acceptance is stale — the
        # others accepted a game against a different deck.
        self._unready(game)
        return game

    def set_banner_color(
        self,
        game_id: str,
        player_id: str,
        color: Optional[str],
        seat_id: Optional[str] = None,
    ) -> LobbyGame:
        """Pick the colours a seat's board banner flies (`Seat.banner_color`).

        Same seat rules as `set_deck` — your own seat, or a bot's if you're
        the host — but, unlike every other setting on the table, this one
        deliberately does **not** clear anybody's acceptance: it changes how
        a banner looks and nothing about the game being agreed to, so
        re-asking the table to accept would be noise.
        """
        game = self._setup_game(game_id)
        seat = self._seat_to_configure(game, player_id, seat_id)
        seat.banner_color = normalize_banner_color(color)
        return game

    @staticmethod
    def _seat_to_configure(
        game: LobbyGame, player_id: str, seat_id: Optional[str]
    ) -> Seat:
        """The seat ``player_id`` is allowed to configure.

        Everyone configures their own seat (``seat_id is None``); the host
        additionally configures a **bot's**, since a bot has no client to do
        it for itself.
        """
        if seat_id is not None and seat_id != player_id:
            seat = game.seat_for(seat_id)
            if seat is None or not seat.is_bot:
                raise LobbyError("you can only configure your own seat")
            if game.host_id != player_id:
                raise LobbyError("only the host can configure a bot's seat")
        else:
            seat = game.seat_for(player_id)
        if seat is None:
            raise LobbyError("you have no seat in this game")
        return seat

    def set_options(
        self,
        game_id: str,
        player_id: str,
        mulligan_style: Optional[str] = None,
        num_players: Optional[int] = None,
        takebacks_per_player: Optional[int] = None,
        randomize_seating: Optional[bool] = None,
        random_starting_player: Optional[bool] = None,
        game_format: Optional[str] = None,
        archenemy_id: Optional[str] = None,
    ) -> LobbyGame:
        """Change the table's shared settings. Host only — everyone else
        accepts them by readying up."""
        game = self._setup_game(game_id)
        if game.host_id != player_id:
            raise LobbyError("only the host can change the game settings")
        if mulligan_style is not None:
            game.mulligan_style = mulligan_style
        if randomize_seating is not None:
            game.randomize_seating = bool(randomize_seating)
        if random_starting_player is not None:
            game.random_starting_player = bool(random_starting_player)
        if num_players is not None:
            # Never below the seats already taken: shrinking a table can't
            # evict anyone who is already sitting at it.
            game.num_players = max(
                len(game.seats), MIN_SEATS, min(int(num_players), MAX_SEATS)
            )
        if takebacks_per_player is not None:
            game.takebacks_per_player = max(0, min(int(takebacks_per_player), MAX_TAKEBACKS_PER_PLAYER))
        if game_format is not None:
            game.game_format = game_format
        if archenemy_id is not None:
            # "" clears back to the default (the host) — same convention
            # `set_banner_color` uses None for "not chosen".
            game.archenemy_id = archenemy_id or None
        self._unready(game)
        return game

    def set_ready(self, game_id: str, player_id: str, ready: bool = True) -> LobbyGame:
        """A player accepts (or un-accepts) the table as configured."""
        game = self._setup_game(game_id)
        seat = game.seat_for(player_id)
        if seat is None:
            raise LobbyError("you have no seat in this game")
        if ready and not seat.deck_id:
            raise LobbyError("choose a deck before accepting")
        seat.ready = bool(ready)
        return game

    def start(self, game_id: str, session_id: str) -> LobbyGame:
        """Mark the table live, behind the `GameSession` the caller built."""
        game = self._setup_game(game_id)
        if not game.all_ready:
            raise LobbyError("not every player has accepted yet")
        game.session_id = session_id
        game.status = RUNNING
        return game

    def record_concession(self, game_id: str, player_id: str) -> LobbyGame:
        game = self.game(game_id)
        if player_id not in game.conceded_ids:
            game.conceded_ids.append(player_id)
        return game

    def finish(self, game_id: str) -> LobbyGame:
        """The game is over: the table stays visible for the review screen,
        but nobody can join it and everyone still in it is free again."""
        game = self.game(game_id)
        game.status = FINISHED
        return game

    def _setup_game(self, game_id: str) -> LobbyGame:
        game = self.game(game_id)
        if game.status != SETUP:
            raise LobbyError("this game has already started")
        return game

    @staticmethod
    def _unready(game: LobbyGame) -> None:
        for seat in game.seats:
            seat.ready = False

    # -- Views ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """The whole lobby, as the Setup screen renders it."""
        return {
            "players": [p.to_dict() for p in self.players()],
            "games": [g.to_dict() for g in self._games.values()],
        }
