"""GET /api/import/archidekt/{deck_id}: server-side proxy for importing a
public decklist from Archidekt.

Reference: backend/ToDo_Backend.md "Import — follow-up from the frontend",
services/archidekt_client.py (the actual fetch). Moxfield's equivalent
(tried client- and server-side) was reverted — genuinely Cloudflare-
blocked — so this router only carries Archidekt for now.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from mtg_analyzer.api.dependencies import get_archidekt_client
from mtg_analyzer.services.archidekt_client import ArchidektClient, ArchidektFetchError

router = APIRouter(prefix="/api/import", tags=["import"])


@router.get("/archidekt/{deck_id:path}")
def import_archidekt_deck(
    deck_id: str, client: ArchidektClient = Depends(get_archidekt_client)
) -> dict[str, str]:
    """`deck_id` may be a bare Archidekt deck id or a full deck URL pasted
    from the browser — `ArchidektClient.fetch_decklist` extracts the id
    either way. `:path` (not the default single-segment converter)
    because a percent-encoded full URL's "/"s are decoded back to literal
    slashes before routing — same reasoning as the reverted Moxfield route."""
    try:
        return client.fetch_decklist(deck_id)
    except ArchidektFetchError as exc:
        status = exc.status if exc.status in (400, 404) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
