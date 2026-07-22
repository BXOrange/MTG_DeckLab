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


class StartReplayRequest(BaseModel):
    """Request body for POST /api/game/replay (Replay / Puzzle mode).

    Provide a full ``replay`` descriptor to load a saved/exported board, or
    omit it to start from a blank board with ``num_players`` (1 = solo puzzle,
    2 = with an opponent; capped at 2 for now).
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


# -- Multiplayer (api/multiplayer.py, services/lobby.py) -------------------
# Every one of these carries the caller's lobby `playerId` — the
# server-assigned id from `/ws/lobby`'s welcome message or POST /connect,
# not the free-text player name (which is neither unique nor authenticated).


class LobbyConnectRequest(BaseModel):
    """Request body for POST /api/multiplayer/connect.

    ``playerId`` is optional: send it to reclaim an existing id after a
    reload, omit it to be given a fresh one.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = "Spieler"
    player_id: Optional[str] = Field(default=None, alias="playerId")


class MultiplayerPlayerRequest(BaseModel):
    """The bare "it's me" body: join/leave/observe/start/concede."""

    model_config = ConfigDict(populate_by_name=True)

    player_id: str = Field(alias="playerId")


class MultiplayerGameRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games (open a table)."""

    name: str = ""
    num_players: int = Field(default=2, alias="numPlayers")


class MultiplayerDeckRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/deck."""

    deck_id: str = Field(alias="deckId")


class MultiplayerOptionsRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/options (host only)."""

    mulligan_style: Optional[str] = Field(default=None, alias="mulliganStyle")
    num_players: Optional[int] = Field(default=None, alias="numPlayers")


class MultiplayerReadyRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/ready."""

    ready: bool = True


class MultiplayerActionRequest(MultiplayerPlayerRequest):
    """Request body for POST /api/multiplayer/games/{id}/action.

    ``action`` is one entry from the caller's own `legal_actions`, in the
    same shape `POST /api/game/{id}/action` takes.
    """

    action: dict
