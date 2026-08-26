"""Server-side proxy for fetching a public decklist from Archidekt.

Reference: docs/implementation-state/Done_Backend.md "Import — follow-up from the frontend".
Unlike Moxfield (tried client- and server-side, reverted both times —
genuinely Cloudflare-blocked, see that ToDo entry), Archidekt's API sits
behind no such protection: a plain, unauthenticated request gets a real
JSON response straight from nginx/Google infra, confirmed live by hand.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import httpx2 as httpx

from mtg_analyzer.config import USER_AGENT

_API_BASE = "https://archidekt.com/api/decks"

#: A deck id pasted as a full URL ("https://archidekt.com/decks/12345/some-
#: deck-name", optionally with a trailing slash/query/fragment) rather than
#: the bare numeric id.
_URL_ID_RE = re.compile(r"archidekt\.com/decks/(\d+)")

#: Archidekt's own deck-level `categories` can flag a category as excluded
#: from the actual decklist (e.g. a "Maybeboard") via `includedInDeck`;
#: cards under such a category shouldn't be imported as list contents.
_COMMANDER_CATEGORY = "Commander"
_SIDEBOARD_CATEGORY = "Sideboard"


class ArchidektFetchError(Exception):
    """The deck couldn't be fetched or didn't look like a deck.

    `status` mirrors the upstream HTTP status where known (404 = no such
    deck) so the API layer can pick a matching response code instead of a
    blanket 502.
    """

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def extract_deck_id(raw: str) -> str:
    """Pull a bare numeric deck id out of a pasted Archidekt deck URL, or
    pass a bare id through unchanged (still validated as digits-only by
    the caller — Archidekt's own ids are always numeric)."""
    raw = (raw or "").strip()
    match = _URL_ID_RE.search(raw)
    if match:
        return match.group(1)
    return raw.rstrip("/").rsplit("/", 1)[-1]


def _card_name(card: dict[str, Any]) -> str:
    return card.get("displayName") or (card.get("oracleCard") or {}).get("name") or ""


def _decklist_sections(data: dict[str, Any]) -> dict[str, str]:
    excluded_categories = {
        category.get("name")
        for category in (data.get("categories") or [])
        if category.get("includedInDeck") is False
    }

    commander_lines: list[str] = []
    mainboard_lines: list[str] = []
    sideboard_lines: list[str] = []

    for entry in data.get("cards") or []:
        categories = entry.get("categories") or []
        if any(category in excluded_categories for category in categories):
            continue

        name = _card_name(entry.get("card") or {})
        if not name:
            continue

        line = f"{entry.get('quantity', 1)} {name}"
        if _COMMANDER_CATEGORY in categories:
            commander_lines.append(line)
        elif _SIDEBOARD_CATEGORY in categories:
            sideboard_lines.append(line)
        else:
            mainboard_lines.append(line)

    return {
        "name": data.get("name") or "",
        "commanderText": "\n".join(commander_lines),
        "mainboardText": "\n".join(mainboard_lines),
        "sideboardText": "\n".join(sideboard_lines),
    }


class ArchidektClient:
    """Thin wrapper around the Archidekt HTTP API used for the import proxy."""

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=10.0
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ArchidektClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_decklist(self, deck_id: str) -> dict[str, str]:
        """Fetch a public Archidekt deck and return it as decklist text
        sections. Shape matches what `POST /api/decks` / `POST
        /api/decks/save` expect: `{name, commanderText, mainboardText,
        sideboardText}`. Raises `ArchidektFetchError` on any failure —
        network, non-200, a non-numeric id, or a body that doesn't look
        like a deck.
        """
        deck_id = extract_deck_id(deck_id)
        if not deck_id.isdigit():
            raise ArchidektFetchError(f'Ungültige Archidekt-Deck-ID: "{deck_id}".', status=400)

        try:
            response = self._client.get(f"{_API_BASE}/{deck_id}/", params={"format": "json"})
        except httpx.HTTPError as exc:
            raise ArchidektFetchError(f"Archidekt nicht erreichbar: {exc}") from exc

        if response.status_code == 404:
            raise ArchidektFetchError(f'Kein Archidekt-Deck mit ID "{deck_id}" gefunden.', status=404)
        if response.status_code != 200:
            raise ArchidektFetchError(
                f"Archidekt-Fehler (HTTP {response.status_code}).", status=response.status_code
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ArchidektFetchError("Ungültige Antwort von Archidekt.", status=response.status_code) from exc

        if not isinstance(data, dict) or "cards" not in data:
            raise ArchidektFetchError(f'Kein Archidekt-Deck mit ID "{deck_id}" gefunden.', status=404)

        return _decklist_sections(data)
