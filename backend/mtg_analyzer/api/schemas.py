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
