"""Per-player custom art + preferences: token images, sleeves, favorite decks.

Reference: `services/player_assets.py` module docstring for the storage
model and why these are keyed by `player_name` rather than a session.

* ``GET/POST /api/players/{name}/token-images``, ``GET .../image?token_name=``,
  ``DELETE .../token-images?token_name=``
* ``GET/POST/DELETE /api/players/{name}/sleeves[/{sleeve_id}]``
* ``GET /api/players/{name}/sleeves/{sleeve_id}/image`` — bytes
* ``GET/POST /api/players/{name}/favorite-decks``,
  ``DELETE /api/players/{name}/favorite-decks/{deck_id}``

Token names are free text a player chooses (matching a token's display
name, e.g. "Soldier 1/1") and can contain a literal ``/`` — a path
segment can't safely round-trip that (a percent-encoded slash doesn't
match a single ``{token_name}`` route segment), so the image/delete
routes take it as a query parameter instead. Sleeves are keyed by a
server-generated UUID with no such issue, so those stay path params.

Uploads are multipart (``UploadFile``), validated against a small
allow-list of image content types and a size cap so an arbitrary file
can't be smuggled in or used to exhaust disk/memory (OWASP unrestricted
file upload).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from mtg_analyzer.api.dependencies import get_player_asset_store
from mtg_analyzer.services.player_assets import PlayerAssetStore

router = APIRouter(prefix="/api/players", tags=["player-assets"])

_ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


async def _read_validated_image(file: UploadFile) -> tuple[str, bytes]:
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            400, f'Unsupported image type "{file.content_type}" (allowed: {sorted(_ALLOWED_CONTENT_TYPES)})'
        )
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty upload")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"Image exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
    return file.content_type, data


# -- Token images ------------------------------------------------------------


@router.get("/{player_name}/token-images")
def list_token_images(
    player_name: str, store: PlayerAssetStore = Depends(get_player_asset_store)
) -> list[dict[str, str]]:
    return store.list_token_images(player_name)


@router.post("/{player_name}/token-images")
async def upload_token_image(
    player_name: str,
    token_name: str = Form(...),
    file: UploadFile = File(...),
    store: PlayerAssetStore = Depends(get_player_asset_store),
) -> dict[str, str]:
    token_name = token_name.strip()
    if not token_name:
        raise HTTPException(400, "token_name must not be empty")
    content_type, data = await _read_validated_image(file)
    store.save_token_image(player_name, token_name, content_type, data)
    return {"token_name": token_name}


@router.get("/{player_name}/token-images/image")
def get_token_image(
    player_name: str, token_name: str, store: PlayerAssetStore = Depends(get_player_asset_store)
) -> Response:
    entry = store.get_token_image(player_name, token_name)
    if entry is None:
        raise HTTPException(404, f'No token image "{token_name}" for player "{player_name}"')
    content_type, data = entry
    return Response(content=data, media_type=content_type)


@router.delete("/{player_name}/token-images")
def delete_token_image(
    player_name: str, token_name: str, store: PlayerAssetStore = Depends(get_player_asset_store)
) -> dict[str, bool]:
    if not store.delete_token_image(player_name, token_name):
        raise HTTPException(404, f'No token image "{token_name}" for player "{player_name}"')
    return {"deleted": True}


# -- Sleeves ------------------------------------------------------------------


@router.get("/{player_name}/sleeves")
def list_sleeves(
    player_name: str, store: PlayerAssetStore = Depends(get_player_asset_store)
) -> list[dict[str, str]]:
    return store.list_sleeves(player_name)


@router.post("/{player_name}/sleeves")
async def upload_sleeve(
    player_name: str,
    label: str = Form(...),
    file: UploadFile = File(...),
    store: PlayerAssetStore = Depends(get_player_asset_store),
) -> dict[str, str]:
    label = label.strip()
    if not label:
        raise HTTPException(400, "label must not be empty")
    content_type, data = await _read_validated_image(file)
    sleeve_id = str(uuid.uuid4())
    store.save_sleeve(player_name, sleeve_id, label, content_type, data)
    return {"sleeve_id": sleeve_id, "label": label}


@router.get("/{player_name}/sleeves/{sleeve_id}/image")
def get_sleeve_image(
    player_name: str, sleeve_id: str, store: PlayerAssetStore = Depends(get_player_asset_store)
) -> Response:
    entry = store.get_sleeve(player_name, sleeve_id)
    if entry is None:
        raise HTTPException(404, f'No sleeve "{sleeve_id}" for player "{player_name}"')
    content_type, data = entry
    return Response(content=data, media_type=content_type)


@router.delete("/{player_name}/sleeves/{sleeve_id}")
def delete_sleeve(
    player_name: str, sleeve_id: str, store: PlayerAssetStore = Depends(get_player_asset_store)
) -> dict[str, bool]:
    if not store.delete_sleeve(player_name, sleeve_id):
        raise HTTPException(404, f'No sleeve "{sleeve_id}" for player "{player_name}"')
    return {"deleted": True}


# -- Favorite decks ------------------------------------------------------


class _FavoriteDeckRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    deck_id: str = Field(alias="deckId")


@router.get("/{player_name}/favorite-decks")
def list_favorite_decks(
    player_name: str, store: PlayerAssetStore = Depends(get_player_asset_store)
) -> list[str]:
    return store.list_favorite_decks(player_name)


@router.post("/{player_name}/favorite-decks")
def add_favorite_deck(
    player_name: str,
    request: _FavoriteDeckRequest,
    store: PlayerAssetStore = Depends(get_player_asset_store),
) -> dict[str, str]:
    deck_id = request.deck_id.strip()
    if not deck_id:
        raise HTTPException(400, "deck_id must not be empty")
    store.add_favorite_deck(player_name, deck_id)
    return {"deck_id": deck_id}


@router.delete("/{player_name}/favorite-decks/{deck_id}")
def remove_favorite_deck(
    player_name: str, deck_id: str, store: PlayerAssetStore = Depends(get_player_asset_store)
) -> dict[str, bool]:
    store.remove_favorite_deck(player_name, deck_id)
    return {"deleted": True}
