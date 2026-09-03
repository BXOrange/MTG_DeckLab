"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CardResolveRequest(BaseModel):
    """Request body for POST /api/cards/resolve: batch name -> Card lookup."""

    names: list[str] = Field(default_factory=list)


class SaveDeckRequest(BaseModel):
    """Request body for POST /api/decks/save.

    `id` is omitted to save a new deck (a UUID is generated) and passed
    back to update one already saved. `name` is just a label — it isn't
    used to look decks up, so it need not be unique.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = None
    name: str = ""
    commander_text: str = Field(default="", alias="commanderText")
    mainboard_text: str = Field(default="", alias="mainboardText")
    sideboard_text: str = Field(default="", alias="sideboardText")
    sleeve_id: Optional[str] = Field(default=None, alias="sleeveId")
    author: Optional[str] = None
    # Same preserve-on-omission treatment as sleeve_id/author: None means
    # "leave whatever this deck already had" rather than "set to False".
    is_cube: Optional[bool] = Field(default=None, alias="isCube")
    # Same preserve-on-omission treatment: None means "leave whatever this
    # deck already had". Must stay None-default, not a mutable/empty-list
    # default — the latter would make "omitted" indistinguishable from
    # "explicitly cleared" and silently wipe the field on every unrelated
    # re-save (e.g. renaming a deck would also erase its archetypes).
    archetypes: Optional[list[str]] = Field(default=None, alias="archetypes")
    favorite_cards: Optional[list[str]] = Field(default=None, alias="favoriteCards")


class DeckSubmission(BaseModel):
    """Request body for POST /api/decks.

    Field names use the frontend's camelCase convention
    (frontend/src/js/parser.js parseDeckSections) via aliases, so the
    same body the client already builds can be posted unchanged.
    """

    model_config = ConfigDict(populate_by_name=True)

    commander_text: str = Field(default="", alias="commanderText")
    mainboard_text: str = Field(default="", alias="mainboardText")
    sideboard_text: str = Field(default="", alias="sideboardText")
    is_cube: bool = Field(default=False, alias="isCube")


class StartGoldfishRequest(BaseModel):
    """Request body for POST /api/game/goldfish (UC3).

    Provide either a saved `deckId` to load, or the decklist text
    directly (same three sections as the rest of the API). `shuffle`
    controls whether the library is randomized (off by default so a
    session is reproducible).
    """

    model_config = ConfigDict(populate_by_name=True)

    deck_id: Optional[str] = Field(default=None, alias="deckId")
    commander_text: str = Field(default="", alias="commanderText")
    mainboard_text: str = Field(default="", alias="mainboardText")
    sideboard_text: str = Field(default="", alias="sideboardText")
    starting_life: int = Field(default=40, alias="startingLife")
    starting_hand: int = Field(default=7, alias="startingHand")
    shuffle: bool = True
    #: PLR-13: a `models/game_format.py` name (Commander/Planechase/…).
    #: Overrides startingLife/startingHand and sets up that format's RULE 9
    #: variant state; omitted/unknown falls back to Commander.
    game_format: Optional[str] = Field(default=None, alias="gameFormat")


class DeckTokensRequest(BaseModel):
    """Request body for POST /api/game/deck-tokens.

    Same deck-source shape as `StartGoldfishRequest` (a saved `deckId` or
    decklist text): returns the tokens the deck can produce so the goldfish
    loading screen can preload their art before the match starts.
    """

    model_config = ConfigDict(populate_by_name=True)

    deck_id: Optional[str] = Field(default=None, alias="deckId")
    commander_text: str = Field(default="", alias="commanderText")
    mainboard_text: str = Field(default="", alias="mainboardText")
    sideboard_text: str = Field(default="", alias="sideboardText")


class DynamicAnalysisRequest(BaseModel):
    """Request body for POST /api/analysis/dynamic (ANA-4).

    Same deck-source shape as `StartGoldfishRequest` (a saved `deckId` or
    decklist text), plus which bot drives the simulated matches and how
    many to run. `numMatches`/`maxTurns` are clamped again in
    `services/dynamic_analysis.py` (`MAX_NUM_MATCHES`/`MAX_MAX_TURNS`) —
    the bounds here just reject an obviously-bad request before it starts a
    background job at all.
    """

    model_config = ConfigDict(populate_by_name=True)

    deck_id: Optional[str] = Field(default=None, alias="deckId")
    commander_text: str = Field(default="", alias="commanderText")
    mainboard_text: str = Field(default="", alias="mainboardText")
    sideboard_text: str = Field(default="", alias="sideboardText")
    bot_kind: str = Field(default="goldfish", alias="botKind")
    num_matches: int = Field(default=20, ge=1, le=200, alias="numMatches")
    max_turns: int = Field(default=10, ge=1, le=30, alias="maxTurns")
    starting_life: int = Field(default=40, alias="startingLife")
    starting_hand: int = Field(default=7, alias="startingHand")
    game_format: Optional[str] = Field(default=None, alias="gameFormat")
    # A per-request simulation input, not a persisted field — empty-list
    # default is fine here (unlike SaveDeckRequest's archetypes/
    # favorite_cards, there's no "omitted vs. explicitly cleared"
    # distinction to preserve for a one-shot simulation run). When
    # `deck_id` is given and this is empty, `api/dynamic_analysis.py` falls
    # back to that deck's own saved `favorite_cards`.
    favorite_cards: list[str] = Field(default_factory=list, alias="favoriteCards")


class ArchetypeAnalysisRequest(BaseModel):
    """Request body for POST /api/archetypes/analyze.

    Same deck-source shape as `DynamicAnalysisRequest`/`StartGoldfishRequest`
    (a saved `deckId`, or decklist text directly).
    """

    model_config = ConfigDict(populate_by_name=True)

    deck_id: Optional[str] = Field(default=None, alias="deckId")
    commander_text: str = Field(default="", alias="commanderText")
    mainboard_text: str = Field(default="", alias="mainboardText")
    sideboard_text: str = Field(default="", alias="sideboardText")


class StartReplayRequest(BaseModel):
    """Request body for POST /api/game/replay (Replay / Puzzle mode).

    Provide a full ``replay`` descriptor to load a saved/exported board, or
    omit it to start from a blank board with ``num_players`` (1 = solo puzzle,
    2-4 = with opponents; capped at 4, same as Multiplayer's `MAX_SEATS`).
    """

    model_config = ConfigDict(populate_by_name=True)

    replay: Optional[dict] = None
    num_players: int = Field(default=1, alias="numPlayers")


class GameActionRequest(BaseModel):
    """Request body for POST /api/game/{id}/action.

    An action mirrors an entry from the session's `legal_actions` (a
    `type` plus optional `instance_id`/`instance_ids`/`targets`).
    """

    model_config = ConfigDict(extra="allow")

    type: str


class RewindRequest(BaseModel):
    """Request body for POST /api/game/{id}/rewind."""

    steps: int = 1


class SaveUiDraftRequest(BaseModel):
    """Request body for POST /api/game/{id}/ui-draft (PLR-6).

    ``playerId`` names whose draft this is — required in multiplayer
    (several real players share one session), omitted in solo modes (the
    one real human). ``draft`` is opaque, caller-defined JSON; ``None``
    clears whatever was stored.
    """

    model_config = ConfigDict(populate_by_name=True)

    player_id: Optional[str] = Field(default=None, alias="playerId")
    draft: Optional[dict] = None


# -- Multiplayer (api/multiplayer.py, services/lobby.py) -------------------
# Every one of these carries the caller's lobby `playerId` — the
# server-assigned id from `/ws/lobby`'s welcome message or POST /connect,
# not the free-text player name (which is neither unique nor authenticated).


class LobbyConnectRequest(BaseModel):
    """Request body for POST /api/multiplayer/connect.

    ``playerId`` is optional: send it to reclaim an existing id after a
    reload, omit it to be given a fresh one. ``clientToken`` (PLR-4) is the
    browser's own identity token (`settings.js`'s `mtg_client_token`
    cookie, minted by profileView.js) — send it once it exists so a
    reconnect resolves by token rather than by the (not-unique) name; see
    `services/lobby.py`'s `Lobby.connect`.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = "Spieler"
    player_id: Optional[str] = Field(default=None, alias="playerId")
    client_token: Optional[str] = Field(default=None, alias="clientToken")


class MultiplayerPlayerRequest(BaseModel):
    """The bare "it's me" body: join/leave/observe/start/concede."""

    model_config = ConfigDict(populate_by_name=True)

    player_id: str = Field(alias="playerId")


class MultiplayerGameRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games (open a table)."""

    name: str = ""
    num_players: int = Field(default=2, alias="numPlayers")


class MultiplayerDeckRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/deck.

    ``seatId`` picks the deck for someone else's seat — only ever a bot's,
    and only by the host, since a bot can't choose for itself. Omitted
    (the normal case) it means "my own seat".
    """

    deck_id: str = Field(alias="deckId")
    seat_id: Optional[str] = Field(default=None, alias="seatId")


class MultiplayerBannerColorRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/banner.

    ``color`` is a banner-colour key (`services/lobby.normalize_banner_color`
    — any subset of ``wubrg``, or ``"c"`` for the grey colourless banner);
    ``seatId`` targets a bot's seat, host only, exactly like the deck route.
    """

    color: str
    seat_id: Optional[str] = Field(default=None, alias="seatId")


class MultiplayerBotRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/bots (host only)."""

    kind: str
    name: str = ""


class MultiplayerBotRemoveRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/bots/remove."""

    bot_id: str = Field(alias="botId")


class MultiplayerOptionsRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/options (host only)."""

    mulligan_style: Optional[str] = Field(default=None, alias="mulliganStyle")
    num_players: Optional[int] = Field(default=None, alias="numPlayers")
    takebacks_per_player: Optional[int] = Field(default=None, alias="takebacksPerPlayer")
    #: RULE 103.1/103.2 — see `LobbyGame.seating_order`.
    randomize_seating: Optional[bool] = Field(default=None, alias="randomizeSeating")
    random_starting_player: Optional[bool] = Field(default=None, alias="randomStartingPlayer")
    #: PLR-13: a `models/game_format.py` name — validated against `FORMATS`
    #: here (unlike the lobby, which stores it as an opaque string).
    game_format: Optional[str] = Field(default=None, alias="gameFormat")
    #: RULE 904: which seat is the Archenemy, when the format has that
    #: variant. A player id, or None for "the host" (`LobbyGame`'s default).
    archenemy_id: Optional[str] = Field(default=None, alias="archenemyId")


class MultiplayerReadyRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/ready."""

    ready: bool = True


class MultiplayerActionRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/action.

    ``action`` is one entry from the caller's own `legal_actions`, in the
    same shape `POST /api/game/{id}/action` takes.
    """

    action: dict


# -- Solo vs. bots (api/solo.py) -----------------------------------------
# The Multiplayer engine (real turns, RULE 117 priority, redacted views)
# minus the lobby: one human, 1-3 bot opponents, plain REST like goldfish.


class SoloOpponent(BaseModel):
    """One bot opponent for POST /api/solo/start."""

    model_config = ConfigDict(populate_by_name=True)

    #: A `services/bots.py` `Bot.kind` (goldfish / greedy / mana_maximizer).
    kind: str = "goldfish"
    #: The saved deck this bot plays — resolved and legality-gated exactly
    #: like the human's (`api/game.resolve_seat_deck`).
    deck_id: str = Field(alias="deckId")


class SoloStartRequest(BaseModel):
    """Request body for POST /api/solo/start.

    ``deckId`` is the human's saved deck; ``opponents`` is 1-3 bots (the
    Multiplayer engine seats 2-4 players). ``startingPlayer`` is ``"you"``
    (default — the human is on the play) or ``"random"`` (seat order is
    shuffled).
    """

    model_config = ConfigDict(populate_by_name=True)

    deck_id: str = Field(alias="deckId")
    opponents: list[SoloOpponent] = Field(default_factory=list)
    mulligan_style: str = Field(default="london", alias="mulliganStyle")
    game_format: Optional[str] = Field(default=None, alias="gameFormat")
    starting_player: str = Field(default="you", alias="startingPlayer")
