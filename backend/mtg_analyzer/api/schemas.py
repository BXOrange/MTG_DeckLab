"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CardResolveRequest(BaseModel):
    """Request body for POST /api/cards/resolve: batch name -> Card lookup."""

    names: list[str] = Field(default_factory=list)


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
