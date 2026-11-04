"""Per-account custom art + preferences: token images, sleeves, favorite decks (PLR-16).

Reference: `services/player_assets.py` module docstring for the storage model.
The owner is always the signed-in account (`current_account`, 401 when anonymous);
there is no name in any URL, so a path can never select another account's assets.
A foreign or missing id is the same 404. Nothing is readable by other accounts.

* ``GET/POST /api/me/token-images``, ``GET .../image?token_name=``,
  ``DELETE .../token-images?token_name=``
* ``GET/POST/DELETE /api/me/sleeves[/{sleeve_id}]``
* ``GET /api/me/sleeves/{sleeve_id}/image`` - bytes
* ``GET/POST /api/me/favorite-decks``,
  ``DELETE /api/me/favorite-decks/{deck_id}``

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

from fastapi import APIRouter, Request, Depends, File, Form, UploadFile
from fastapi.responses import Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from mtg_analyzer.i18n import api_error, error_from
from mtg_analyzer.api.auth import AuthContext, current_account
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
                raise api_error(413, "upload_too_large", limit_mb=_MAX_UPLOAD_BYTES // (1024 * 1024))
            return await original(request)

        return handler


router = APIRouter(prefix="/api/me", tags=["player-assets"], route_class=_BoundedBodyRoute)

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
        raise api_error(
            400, "upload_unsupported_type",
            content_type=file.content_type, allowed=", ".join(sorted(_ALLOWED_CONTENT_TYPES)),
        )
    # BUG-43: read in chunks and stop as soon as the limit is crossed, so an
    # oversized body is never held in memory whole.
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(config.UPLOAD_READ_CHUNK_BYTES):
        size += len(chunk)
        if size > _MAX_UPLOAD_BYTES:
            raise api_error(413, "upload_too_large", limit_mb=_MAX_UPLOAD_BYTES // (1024 * 1024))
        chunks.append(chunk)
    if not size:
        raise api_error(400, "upload_empty")
    data = b"".join(chunks)
    if not _matches_magic(file.content_type, data):
        raise api_error(400, "upload_invalid_image", content_type=file.content_type)
    return file.content_type, data


def _save_or_413(save, *args) -> None:
    """Run a store save, turning a quota refusal into HTTP 413."""
    try:
        save(*args)
    except AssetQuotaError as exc:
        raise error_from(exc, 413) from exc


# -- Token images ------------------------------------------------------------


@router.get("/token-images")
def list_token_images(
    store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> list[dict[str, str]]:
    return store.list_token_images(ctx.account.player_uuid)


@router.post("/token-images")
async def upload_token_image(
    token_name: str = Form(...),
    file: UploadFile = File(...),
    store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> dict[str, str]:
    token_name = token_name.strip()
    if not token_name:
        raise api_error(400, "token_name_empty")
    content_type, data = await _read_validated_image(file)
    _save_or_413(store.save_token_image, ctx.account.player_uuid, token_name, content_type, data)
    return {"token_name": token_name}


@router.get("/token-images/image")
def get_token_image(
    token_name: str, store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> Response:
    entry = store.get_token_image(ctx.account.player_uuid, token_name)
    if entry is None:
        raise api_error(404, "token_image_not_found", token_name=token_name)
    content_type, data = entry
    return _image_response(content_type, data)


@router.delete("/token-images")
def delete_token_image(
    token_name: str, store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> dict[str, bool]:
    if not store.delete_token_image(ctx.account.player_uuid, token_name):
        raise api_error(404, "token_image_not_found", token_name=token_name)
    return {"deleted": True}


# -- Sleeves ------------------------------------------------------------------


@router.get("/sleeves")
def list_sleeves(
    store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> list[dict[str, str]]:
    return store.list_sleeves(ctx.account.player_uuid)


@router.post("/sleeves")
async def upload_sleeve(
    label: str = Form(...),
    file: UploadFile = File(...),
    store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> dict[str, str]:
    label = label.strip()
    if not label:
        raise api_error(400, "label_empty")
    content_type, data = await _read_validated_image(file)
    sleeve_id = str(uuid.uuid4())
    _save_or_413(store.save_sleeve, ctx.account.player_uuid, sleeve_id, label, content_type, data)
    return {"sleeve_id": sleeve_id, "label": label}


@router.get("/sleeves/{sleeve_id}/image")
def get_sleeve_image(
    sleeve_id: str, store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> Response:
    entry = store.get_sleeve(ctx.account.player_uuid, sleeve_id)
    if entry is None:
        raise api_error(404, "sleeve_not_found", sleeve_id=sleeve_id)
    content_type, data = entry
    return _image_response(content_type, data)


@router.delete("/sleeves/{sleeve_id}")
def delete_sleeve(
    sleeve_id: str, store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> dict[str, bool]:
    if not store.delete_sleeve(ctx.account.player_uuid, sleeve_id):
        raise api_error(404, "sleeve_not_found", sleeve_id=sleeve_id)
    return {"deleted": True}


# -- Favorite decks ------------------------------------------------------


class _FavoriteDeckRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    deck_id: str = Field(alias="deckId")


@router.get("/favorite-decks")
def list_favorite_decks(
    store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> list[str]:
    return store.list_favorite_decks(ctx.account.player_uuid)


@router.post("/favorite-decks")
def add_favorite_deck(
    request: _FavoriteDeckRequest,
    store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> dict[str, str]:
    deck_id = request.deck_id.strip()
    if not deck_id:
        raise api_error(400, "deck_id_empty")
    store.add_favorite_deck(ctx.account.player_uuid, deck_id)
    return {"deck_id": deck_id}


@router.delete("/favorite-decks/{deck_id}")
def remove_favorite_deck(
    deck_id: str, store: PlayerAssetStore = Depends(get_player_asset_store),
    ctx: AuthContext = Depends(current_account),
) -> dict[str, bool]:
    store.remove_favorite_deck(ctx.account.player_uuid, deck_id)
    return {"deleted": True}
