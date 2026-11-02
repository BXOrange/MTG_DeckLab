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

from typing import Callable

from fastapi import APIRouter, Request, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from mtg_analyzer.api.dependencies import get_player_asset_store
from mtg_analyzer import config
from mtg_analyzer.security_headers import ASSET_CSP
from mtg_analyzer.services.player_assets import AssetQuotaError, PlayerAssetStore



class _BoundedBodyRoute(APIRoute):
    """BUG-43: refuse an oversized POST by Content-Length *before* the form is parsed.

    FastAPI parses the multipart body (spooling every file) before dependencies
    run, so only the route handler wrapper sees the request early enough. The
    chunked read in `_read_validated_image` stays as the second line for bodies
    without a trustworthy Content-Length.
    """

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            declared = request.headers.get("content-length", "")
            limit = _MAX_UPLOAD_BYTES + config.UPLOAD_MULTIPART_OVERHEAD_BYTES
            if request.method == "POST" and declared.isdigit() and int(declared) > limit:
                raise HTTPException(413, f"Upload exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
            return await original(request)

        return handler


router = APIRouter(prefix="/api/players", tags=["player-assets"], route_class=_BoundedBodyRoute)

_ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MAX_UPLOAD_BYTES = config.PLAYER_UPLOAD_MAX_BYTES

#: BUG-44: file signatures per allowed content type, so a client cannot label
#: arbitrary bytes (HTML, SVG, script) as an image. WebP is `RIFF<size>WEBP`.
_WEBP_RIFF, _WEBP_FORM, _WEBP_FORM_OFFSET = b"RIFF", b"WEBP", 8
_MAGIC_PREFIXES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}


def _matches_magic(content_type: str, data: bytes) -> bool:
    if content_type == "image/webp":
        return (data.startswith(_WEBP_RIFF)
                and data[_WEBP_FORM_OFFSET:_WEBP_FORM_OFFSET + len(_WEBP_FORM)] == _WEBP_FORM)
    return data.startswith(_MAGIC_PREFIXES[content_type])


def _image_response(content_type: str, data: bytes) -> Response:
    """Serve stored bytes inert: declared type only (nosniff comes from the
    middleware), and a CSP that forbids loading or running anything."""
    return Response(content=data, media_type=content_type, headers={
        "Content-Security-Policy": ASSET_CSP,
        "X-Content-Type-Options": "nosniff",
    })


async def _read_validated_image(file: UploadFile) -> tuple[str, bytes]:
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            400, f'Unsupported image type "{file.content_type}" (allowed: {sorted(_ALLOWED_CONTENT_TYPES)})'
        )
    # BUG-43: read in chunks and stop as soon as the limit is crossed, so an
    # oversized body is never held in memory whole.
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(config.UPLOAD_READ_CHUNK_BYTES):
        size += len(chunk)
        if size > _MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Image exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
        chunks.append(chunk)
    if not size:
        raise HTTPException(400, "Empty upload")
    data = b"".join(chunks)
    if not _matches_magic(file.content_type, data):
        raise HTTPException(400, f'File content is not a valid "{file.content_type}" image')
    return file.content_type, data


def _save_or_413(save, *args) -> None:
    """Run a store save, turning a quota refusal into HTTP 413."""
    try:
        save(*args)
    except AssetQuotaError as exc:
        raise HTTPException(413, str(exc)) from exc


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
    _save_or_413(store.save_token_image, player_name, token_name, content_type, data)
    return {"token_name": token_name}


@router.get("/{player_name}/token-images/image")
def get_token_image(
    player_name: str, token_name: str, store: PlayerAssetStore = Depends(get_player_asset_store)
) -> Response:
    entry = store.get_token_image(player_name, token_name)
    if entry is None:
        raise HTTPException(404, f'No token image "{token_name}" for player "{player_name}"')
    content_type, data = entry
    return _image_response(content_type, data)


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
    _save_or_413(store.save_sleeve, player_name, sleeve_id, label, content_type, data)
    return {"sleeve_id": sleeve_id, "label": label}


@router.get("/{player_name}/sleeves/{sleeve_id}/image")
def get_sleeve_image(
    player_name: str, sleeve_id: str, store: PlayerAssetStore = Depends(get_player_asset_store)
) -> Response:
    entry = store.get_sleeve(player_name, sleeve_id)
    if entry is None:
        raise HTTPException(404, f'No sleeve "{sleeve_id}" for player "{player_name}"')
    content_type, data = entry
    return _image_response(content_type, data)


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
